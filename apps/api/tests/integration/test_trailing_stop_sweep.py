"""Integration tests — ``TrailingStopSweepService.sweep`` end-to-end.

Slice ``orchestration-trailing-stops-cron`` task 8. Verifies the 10
acceptance scenarios from the proposal §Tests: inert-when-cap-None,
zero-trades-no-op, audit-row-on-trailed, no-row-on-no-update,
no-row-on-trigger-not-reached, current-stop-resolves-from-audit-then-
proposal, short-side skip, per-symbol exception isolation, tenant
scoping.

Reuses the ``schema_session_factory`` from the integration conftest:
schema built via ``Base.metadata.create_all`` so the new
``trailing_stop_audit`` table comes online when the ORM module is
imported.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.risk.models import RiskCaps

# Importing the ORM module registers TrailingStopAuditORM on the shared
# Base.metadata so the conftest's create_all builds the table.
from iguanatrader.contexts.risk.orm import (
    TrailingStopAuditORM,
)
from iguanatrader.contexts.risk.trailing_stop_repository import (
    TrailingStopAuditRepository,
)
from iguanatrader.contexts.risk.trailing_stop_sweep import (
    TrailingStopSweepService,
)
from iguanatrader.contexts.trading.models import StrategyConfig, Trade, TradeProposal
from iguanatrader.contexts.trading.ports import Bar, BarHistory
from iguanatrader.persistence import Tenant
from iguanatrader.shared.contextvars import (
    run_in_session_scope,
    with_tenant_context,
)
from iguanatrader.shared.time import now as utc_now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _FakeMarketDataPort:
    """In-memory ``MarketDataPort`` returning seeded bars per symbol.

    Tests register a list of bars per symbol; ``raise_for_symbol``
    triggers a controlled error for the failure-isolation scenario.
    """

    def __init__(self) -> None:
        self._bars_by_symbol: dict[str, list[Bar]] = {}
        self._raise_for_symbol: set[str] = set()

    def set_bars(self, symbol: str, bars: list[Bar]) -> None:
        self._bars_by_symbol[symbol] = bars

    def raise_for(self, symbol: str) -> None:
        self._raise_for_symbol.add(symbol)

    async def get_bars(
        self,
        *,
        symbol: str,
        timeframe: Literal["1d", "1h", "1m"],
        lookback_bars: int,
        as_of: datetime | None = None,
    ) -> BarHistory:
        if symbol in self._raise_for_symbol:
            raise RuntimeError(f"fake market-data fetch failed for {symbol}")
        return BarHistory(symbol=symbol, bars=self._bars_by_symbol.get(symbol, []))


def _make_bar(*, ts: datetime, close: Decimal, high: Decimal | None = None) -> Bar:
    """Compact helper — high/low default to close ± 0.5 to satisfy true-range."""
    h = high if high is not None else close + Decimal("0.5")
    return Bar(
        timestamp=ts,
        open=close,
        high=h,
        low=close - Decimal("0.5"),
        close=close,
        volume=Decimal("1000"),
    )


async def _seed_tenant(
    sf: async_sessionmaker[AsyncSession],
    name: str,
) -> UUID:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=name, feature_flags={}))
        await s.commit()
    return tid


async def _seed_strategy_config(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str,
) -> UUID:
    """INSERT a strategy_configs row so TradeProposal's FK resolves."""
    sc_id = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            StrategyConfig(
                id=sc_id,
                tenant_id=tenant_id,
                strategy_kind="donchian_atr",
                symbol=symbol,
                params={"lookback": 20},
                enabled=True,
            )
        )
        await s.commit()
    return sc_id


async def _seed_trade(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str,
    side: str = "buy",
    entry_price: Decimal = Decimal("100"),
    stop_price: Decimal = Decimal("90"),
    state: str = "open",
    opened_at: datetime | None = None,
) -> UUID:
    """INSERT strategy_config + proposal + Trade rows scoped to ``tenant_id``.

    Three commits because the append-only listener evaluates each
    INSERT's FKs against committed rows; the proposal needs the
    strategy_config to exist at proposal-INSERT time, and the trade
    needs the proposal to exist at trade-INSERT time.
    """
    sc_id = await _seed_strategy_config(sf, tenant_id=tenant_id, symbol=symbol)
    proposal_id = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            TradeProposal(
                id=proposal_id,
                tenant_id=tenant_id,
                strategy_config_id=sc_id,
                research_brief_id=None,
                correlation_id=uuid4(),
                symbol=symbol,
                side=side,
                quantity=Decimal("10"),
                entry_price_indicative=entry_price,
                stop_price=stop_price,
                reasoning={"why": "test"},
                mode="paper",
            )
        )
        await s.commit()

    trade_id = uuid4()
    opened = opened_at if opened_at is not None else utc_now()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            Trade(
                id=trade_id,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol=symbol,
                side=side,
                quantity=Decimal("10"),
                mode="paper",
                state=state,
                opened_at=opened,
            )
        )
        await s.commit()
    return trade_id


async def _count_audit_rows(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
) -> int:
    async with with_tenant_context(tenant_id), sf() as s:
        result = await s.execute(select(TrailingStopAuditORM))
        return len(list(result.scalars().all()))


def _caps_with_trail(trigger_pct: Decimal | None = Decimal("0.03")) -> RiskCaps:
    return RiskCaps(
        trail_trigger_pct=trigger_pct,
        trail_atr_mult=Decimal("1.5"),
        trail_atr_period=14,
    )


# ---------------------------------------------------------------------------
# 1. Inert-when-cap-None.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_short_circuits_when_trail_trigger_pct_is_none(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``trail_trigger_pct=None`` → all-zero result, no DB writes."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-inert")
    await _seed_trade(schema_session_factory, tenant_id=tenant_id, symbol="SPY")

    md = _FakeMarketDataPort()
    md.set_bars("SPY", [_make_bar(ts=utc_now(), close=Decimal("110"))])

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        audit_repo = TrailingStopAuditRepository(s)
        service = TrailingStopSweepService(
            session=s,
            audit_repo=audit_repo,
            risk_caps_provider=lambda: _caps_with_trail(trigger_pct=None),
            market_data_port=md,
        )
        result = await service.sweep()

    assert result.trades_evaluated == 0
    assert result.trades_trailed == 0
    assert await _count_audit_rows(schema_session_factory, tenant_id=tenant_id) == 0


# ---------------------------------------------------------------------------
# 2. Zero open trades.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_zero_open_trades_returns_zero_evaluated(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cap enabled but no open trades → clean zero-result."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-empty-trades")

    md = _FakeMarketDataPort()

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        audit_repo = TrailingStopAuditRepository(s)
        service = TrailingStopSweepService(
            session=s,
            audit_repo=audit_repo,
            risk_caps_provider=_caps_with_trail,
            market_data_port=md,
        )
        result = await service.sweep()

    assert result.trades_evaluated == 0
    assert result.trades_trailed == 0
    assert result.trades_no_update == 0
    assert result.trades_trigger_not_reached == 0
    assert result.trades_skipped_no_bars == 0


# ---------------------------------------------------------------------------
# 3. Audit row inserted on `trailed`.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_persists_audit_row_on_trailed(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Favorable move + ATR distance > current stop → audit row inserted."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-trail")
    opened_at = utc_now() - timedelta(days=5)
    await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_id,
        symbol="SPY",
        entry_price=Decimal("100"),
        stop_price=Decimal("90"),
        opened_at=opened_at,
    )

    md = _FakeMarketDataPort()
    # Build 5 post-entry bars climbing from 105 → 115 (15% favorable move,
    # well above 3% trigger). With ATR ~= 1 and mult 1.5, candidate stop
    # ~= 115 - 1.5 = 113.5 > current 90 → trailed.
    base = opened_at + timedelta(days=1)
    md.set_bars(
        "SPY",
        [_make_bar(ts=base + timedelta(days=i), close=Decimal(105 + i * 2)) for i in range(6)],
    )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        audit_repo = TrailingStopAuditRepository(s)
        service = TrailingStopSweepService(
            session=s,
            audit_repo=audit_repo,
            risk_caps_provider=_caps_with_trail,
            market_data_port=md,
        )
        result = await service.sweep()

    assert result.trades_evaluated == 1
    assert result.trades_trailed == 1
    assert await _count_audit_rows(schema_session_factory, tenant_id=tenant_id) == 1


# ---------------------------------------------------------------------------
# 4. No audit row on `no_update` (pullback after prior ratchet).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_no_audit_row_on_no_update(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Trade with prior audit row at high stop → second sweep w/ pullback no-ops."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-noupdate")
    opened_at = utc_now() - timedelta(days=10)
    trade_id = await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_id,
        symbol="SPY",
        entry_price=Decimal("100"),
        stop_price=Decimal("90"),
        opened_at=opened_at,
    )

    # Pre-seed an audit row putting the current stop way up at 115 — any
    # candidate computed from the bars below will be lower, so no ratchet.
    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        repo = TrailingStopAuditRepository(s)
        await repo.add_row(
            tenant_id=tenant_id,
            trade_id=trade_id,
            swept_at=utc_now() - timedelta(hours=1),
            old_stop=Decimal("90"),
            new_stop=Decimal("115"),
            highest_close_since_entry=Decimal("117"),
            atr=Decimal("1.33"),
            bars_evaluated=5,
        )
        await s.commit()

    md = _FakeMarketDataPort()
    base = opened_at + timedelta(days=1)
    # Bars climb but candidate (~highest - 1.5 * ATR) stays below 115.
    md.set_bars(
        "SPY",
        [_make_bar(ts=base + timedelta(days=i), close=Decimal(105 + i)) for i in range(6)],
    )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        audit_repo = TrailingStopAuditRepository(s)
        service = TrailingStopSweepService(
            session=s,
            audit_repo=audit_repo,
            risk_caps_provider=_caps_with_trail,
            market_data_port=md,
        )
        result = await service.sweep()

    assert result.trades_evaluated == 1
    assert result.trades_no_update == 1
    assert result.trades_trailed == 0
    # Pre-seeded row counts; no NEW row.
    assert await _count_audit_rows(schema_session_factory, tenant_id=tenant_id) == 1


# ---------------------------------------------------------------------------
# 5. No audit row on `trigger_not_reached` (favorable move below trigger).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_no_audit_row_on_trigger_not_reached(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Favorable move below 3% trigger → no audit row, no_update counter zero."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-trigger")
    opened_at = utc_now() - timedelta(days=3)
    await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_id,
        symbol="SPY",
        entry_price=Decimal("100"),
        stop_price=Decimal("90"),
        opened_at=opened_at,
    )

    md = _FakeMarketDataPort()
    base = opened_at + timedelta(days=1)
    # 1% favorable move only — below 3% trigger.
    md.set_bars(
        "SPY",
        [
            _make_bar(ts=base + timedelta(days=i), close=Decimal("100") + Decimal("0.5") * i)
            for i in range(3)
        ],
    )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        audit_repo = TrailingStopAuditRepository(s)
        service = TrailingStopSweepService(
            session=s,
            audit_repo=audit_repo,
            risk_caps_provider=_caps_with_trail,
            market_data_port=md,
        )
        result = await service.sweep()

    assert result.trades_evaluated == 1
    assert result.trades_trigger_not_reached == 1
    assert result.trades_trailed == 0
    assert await _count_audit_rows(schema_session_factory, tenant_id=tenant_id) == 0


# ---------------------------------------------------------------------------
# 6. Current stop resolved from latest audit row.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_resolves_current_stop_from_latest_audit_row(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Pre-seeded audit at stop=80, candidate computed from bars > 80 → trailed."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-resolve-audit")
    opened_at = utc_now() - timedelta(days=10)
    trade_id = await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_id,
        symbol="SPY",
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),  # proposal stop higher than what we'll seed
        opened_at=opened_at,
    )

    # Seed an audit row with new_stop=80 — explicitly LOWER than the
    # proposal stop. If the resolver wrongly used the proposal stop,
    # the candidate (computed from below-95 bars) would fail to ratchet;
    # using the audit row's 80 lets the candidate (~110) clearly exceed.
    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        repo = TrailingStopAuditRepository(s)
        await repo.add_row(
            tenant_id=tenant_id,
            trade_id=trade_id,
            swept_at=utc_now() - timedelta(hours=1),
            old_stop=Decimal("95"),
            new_stop=Decimal("80"),
            highest_close_since_entry=Decimal("100"),
            atr=Decimal("1"),
            bars_evaluated=3,
        )
        await s.commit()

    md = _FakeMarketDataPort()
    base = opened_at + timedelta(days=1)
    md.set_bars(
        "SPY",
        [_make_bar(ts=base + timedelta(days=i), close=Decimal(108 + i)) for i in range(5)],
    )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        audit_repo = TrailingStopAuditRepository(s)
        service = TrailingStopSweepService(
            session=s,
            audit_repo=audit_repo,
            risk_caps_provider=_caps_with_trail,
            market_data_port=md,
        )
        result = await service.sweep()

    assert result.trades_trailed == 1
    # Pre-seed + new ratchet = 2 audit rows.
    assert await _count_audit_rows(schema_session_factory, tenant_id=tenant_id) == 2


# ---------------------------------------------------------------------------
# 7. Current stop fallback to TradeProposal.stop_price.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_resolves_current_stop_from_proposal_when_no_audit(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No prior audit → ``TradeProposal.stop_price`` is the current stop."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-resolve-proposal")
    opened_at = utc_now() - timedelta(days=5)
    await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_id,
        symbol="SPY",
        entry_price=Decimal("100"),
        stop_price=Decimal("90"),
        opened_at=opened_at,
    )

    md = _FakeMarketDataPort()
    base = opened_at + timedelta(days=1)
    md.set_bars(
        "SPY",
        [_make_bar(ts=base + timedelta(days=i), close=Decimal(105 + i * 2)) for i in range(5)],
    )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        audit_repo = TrailingStopAuditRepository(s)
        service = TrailingStopSweepService(
            session=s,
            audit_repo=audit_repo,
            risk_caps_provider=_caps_with_trail,
            market_data_port=md,
        )
        result = await service.sweep()

    assert result.trades_trailed == 1
    assert await _count_audit_rows(schema_session_factory, tenant_id=tenant_id) == 1


# ---------------------------------------------------------------------------
# 8. Short-side trades short-circuit (no audit row).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_skips_short_trades(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sell-side trade → pure function returns trigger_not_reached, no audit row."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-short")
    opened_at = utc_now() - timedelta(days=5)
    await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_id,
        symbol="SPY",
        side="sell",
        entry_price=Decimal("100"),
        stop_price=Decimal("110"),
        opened_at=opened_at,
    )

    md = _FakeMarketDataPort()
    base = opened_at + timedelta(days=1)
    md.set_bars(
        "SPY",
        [_make_bar(ts=base + timedelta(days=i), close=Decimal(90 - i)) for i in range(5)],
    )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        audit_repo = TrailingStopAuditRepository(s)
        service = TrailingStopSweepService(
            session=s,
            audit_repo=audit_repo,
            risk_caps_provider=_caps_with_trail,
            market_data_port=md,
        )
        result = await service.sweep()

    assert result.trades_evaluated == 1
    assert result.trades_trigger_not_reached == 1
    assert result.trades_trailed == 0
    assert await _count_audit_rows(schema_session_factory, tenant_id=tenant_id) == 0


# ---------------------------------------------------------------------------
# 9. Per-symbol failure isolation.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_continues_after_per_symbol_failure(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """One symbol raises, others continue. Skipped count == 1, no abort."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-isolate")
    opened_at = utc_now() - timedelta(days=5)
    await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_id,
        symbol="AAPL",
        entry_price=Decimal("100"),
        stop_price=Decimal("90"),
        opened_at=opened_at,
    )
    await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_id,
        symbol="MSFT",
        entry_price=Decimal("200"),
        stop_price=Decimal("180"),
        opened_at=opened_at,
    )

    md = _FakeMarketDataPort()
    base = opened_at + timedelta(days=1)
    md.raise_for("AAPL")
    md.set_bars(
        "MSFT",
        [_make_bar(ts=base + timedelta(days=i), close=Decimal(210 + i * 5)) for i in range(5)],
    )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        audit_repo = TrailingStopAuditRepository(s)
        service = TrailingStopSweepService(
            session=s,
            audit_repo=audit_repo,
            risk_caps_provider=_caps_with_trail,
            market_data_port=md,
        )
        result = await service.sweep()

    assert result.trades_skipped_no_bars == 1
    assert result.trades_trailed == 1
    # AAPL contributes 0 audit rows (errored); MSFT contributes 1.
    assert await _count_audit_rows(schema_session_factory, tenant_id=tenant_id) == 1


# ---------------------------------------------------------------------------
# 10. Tenant scoping — tenant A's sweep does not touch tenant B's data.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_is_tenant_scoped(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two tenants, each with one open trade. Sweep for A ignores B."""
    tenant_a = await _seed_tenant(schema_session_factory, "t-a")
    tenant_b = await _seed_tenant(schema_session_factory, "t-b")
    opened_at = utc_now() - timedelta(days=5)
    await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_a,
        symbol="SPY",
        entry_price=Decimal("100"),
        stop_price=Decimal("90"),
        opened_at=opened_at,
    )
    await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_b,
        symbol="SPY",
        entry_price=Decimal("200"),
        stop_price=Decimal("180"),
        opened_at=opened_at,
    )

    md = _FakeMarketDataPort()
    base = opened_at + timedelta(days=1)
    md.set_bars(
        "SPY",
        [_make_bar(ts=base + timedelta(days=i), close=Decimal(108 + i * 2)) for i in range(5)],
    )

    # Run sweep ONLY for tenant A.
    async with with_tenant_context(tenant_a), schema_session_factory() as s:
        audit_repo = TrailingStopAuditRepository(s)
        service = TrailingStopSweepService(
            session=s,
            audit_repo=audit_repo,
            risk_caps_provider=_caps_with_trail,
            market_data_port=md,
        )
        result = await service.sweep()

    assert result.trades_evaluated == 1
    assert result.trades_trailed == 1
    assert await _count_audit_rows(schema_session_factory, tenant_id=tenant_a) == 1
    # Tenant B's audit table is untouched.
    assert await _count_audit_rows(schema_session_factory, tenant_id=tenant_b) == 0


# ---------------------------------------------------------------------------
# 11. #29 (cron side): the sweep runs durably through the per-tick
#     unit-of-work wrapper with NO explicit session — it resolves the fresh
#     session ``run_in_session_scope`` binds and the audit row commits at the
#     tick boundary (visible from a fresh session afterwards).
# ---------------------------------------------------------------------------
class _NullBus:
    """Minimal bus for ``run_in_session_scope``; the trailing sweep publishes
    nothing so ``publish`` is never actually reached."""

    async def publish(self, event: object) -> None:  # pragma: no cover - unused
        raise AssertionError("trailing sweep should not publish events")


@pytest.mark.asyncio
async def test_sweep_persists_through_per_tick_unit_of_work_without_explicit_session(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No ``session=...``: the sweep resolves the per-tick session bound by
    ``run_in_session_scope`` and the ratchet commits durably at the boundary."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-pertick")
    opened_at = utc_now() - timedelta(days=5)
    await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_id,
        symbol="SPY",
        entry_price=Decimal("100"),
        stop_price=Decimal("90"),
        opened_at=opened_at,
    )

    md = _FakeMarketDataPort()
    base = opened_at + timedelta(days=1)
    md.set_bars(
        "SPY",
        [_make_bar(ts=base + timedelta(days=i), close=Decimal(105 + i * 2)) for i in range(6)],
    )

    # Construct BOTH the audit repo and the sweep with NO explicit session —
    # exactly the daemon wiring. They resolve session_var, which the wrapper
    # binds per tick.
    audit_repo = TrailingStopAuditRepository()
    service = TrailingStopSweepService(
        audit_repo=audit_repo,
        risk_caps_provider=_caps_with_trail,
        market_data_port=md,
    )

    result = await run_in_session_scope(
        schema_session_factory,
        _NullBus(),
        tenant_id,
        service.sweep,
    )

    assert result.trades_evaluated == 1
    assert result.trades_trailed == 1
    # Durable: a brand-new session sees the committed audit row.
    assert await _count_audit_rows(schema_session_factory, tenant_id=tenant_id) == 1
