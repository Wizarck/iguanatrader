"""Integration tests — ``RiskRepository.load_risk_state`` composed read.

Slice ``wire-risk-state-real-data``. Verifies the 10 acceptance
scenarios from the proposal §Tests: empty fallback, open-count,
latest+peak equity, drawdown, day/week loss percentages,
stoploss-guard tally, per-symbol cooldown dict, tenant scoping.

Uses the slice-K1 ``schema_session_factory`` from
``apps/api/tests/integration/conftest.py``: schema is built from
``Base.metadata.create_all`` (NOT Alembic), tenant listener is
auto-registered, and seeded rows are scoped via
``with_tenant_context``. Each test wraps the load call in
``with_tenant_context`` so the slice-3 listener injects ``WHERE
tenant_id = :ctx`` on every helper SELECT.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

# Importing the ORM module registers the risk tables on the shared
# Base.metadata so the conftest's Base.metadata.create_all builds them.
from iguanatrader.contexts.risk.orm import (  # noqa: F401
    KillSwitchEventORM,
    KillSwitchStateORM,
    RiskEvaluationORM,
    RiskOverrideORM,
)
from iguanatrader.contexts.risk.repository import RiskRepository
from iguanatrader.contexts.trading.models import (
    EquitySnapshot,
    Trade,
    TradeProposal,
)
from iguanatrader.persistence import Tenant
from iguanatrader.shared.contextvars import with_tenant_context
from iguanatrader.shared.time import now as utc_now
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def session(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session with the schema applied."""
    async with schema_session_factory() as s:
        yield s


async def _seed_tenant(
    sf: async_sessionmaker[AsyncSession],
    name: str,
) -> UUID:
    """INSERT a ``tenants`` row and return its id (cross-tenant table)."""
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=name, feature_flags={}))
        await s.commit()
    return tid


async def _seed_proposal(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str = "SPY",
) -> UUID:
    """INSERT a ``trade_proposals`` row scoped to ``tenant_id``."""
    pid = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            TradeProposal(
                id=pid,
                tenant_id=tenant_id,
                strategy_config_id=uuid4(),
                research_brief_id=None,
                correlation_id=uuid4(),
                symbol=symbol,
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("100"),
                stop_price=Decimal("90"),
                reasoning={"why": "test"},
                mode="paper",
            )
        )
        await s.commit()
    return pid


async def _seed_trade(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str = "SPY",
    state: str = "open",
    opened_offset_seconds: int = 0,
    closed_offset_seconds: int | None = None,
    exit_reason: str | None = None,
    realised_pnl: Decimal | None = None,
) -> UUID:
    """INSERT a proposal + a single ``trades`` row.

    ``opened_offset_seconds`` / ``closed_offset_seconds`` are added to
    ``utc_now()`` to position the trade in time. ``None`` for
    ``closed_offset_seconds`` keeps ``closed_at`` NULL (open trade).
    """
    proposal_id = await _seed_proposal(sf, tenant_id=tenant_id, symbol=symbol)
    base = utc_now()
    opened_at = base + timedelta(seconds=opened_offset_seconds)
    closed_at = (
        base + timedelta(seconds=closed_offset_seconds)
        if closed_offset_seconds is not None
        else None
    )
    trade_id = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            Trade(
                id=trade_id,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol=symbol,
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state=state,
                opened_at=opened_at,
                closed_at=closed_at,
                exit_reason=exit_reason,
                realised_pnl=realised_pnl,
            )
        )
        await s.commit()
    return trade_id


async def _seed_equity_snapshot(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    account_equity: Decimal,
    offset_seconds: int = 0,
) -> None:
    """INSERT a single ``equity_snapshots`` row at ``now + offset``."""
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            EquitySnapshot(
                id=uuid4(),
                tenant_id=tenant_id,
                mode="paper",
                account_equity=account_equity,
                cash_balance=Decimal("0"),
                realized_pnl_today=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                currency="USD",
                snapshot_kind="event",
                created_at=utc_now() + timedelta(seconds=offset_seconds),
            )
        )
        await s.commit()


# ---------------------------------------------------------------------------
# 1. Empty tenant → fallback state.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_tenant_returns_fallback_state(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No trades, no equity → capital=10000, all pct = 0, dicts empty."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-empty")

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        repo = RiskRepository(s)
        state = await repo.load_risk_state(tenant_id)

    assert state.capital == Decimal("10000")
    assert state.day_to_date_loss_pct == Decimal("0")
    assert state.week_to_date_loss_pct == Decimal("0")
    assert state.open_positions_count == 0
    assert state.peak_to_trough_drawdown_pct == Decimal("0")
    assert state.recent_stoploss_count_trailing == 0
    assert state.recent_trades_lookback == 0
    assert state.seconds_since_last_close_by_symbol == {}


# ---------------------------------------------------------------------------
# 2. Open count.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_open_trades_counted_correctly(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Seed 3 open + 2 closed → ``open_positions_count == 3``."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-open-count")
    for _ in range(3):
        await _seed_trade(
            schema_session_factory,
            tenant_id=tenant_id,
            state="open",
        )
    for _ in range(2):
        await _seed_trade(
            schema_session_factory,
            tenant_id=tenant_id,
            state="closed_filled",
            closed_offset_seconds=-60,
            exit_reason="target",
            realised_pnl=Decimal("25"),
        )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        state = await RiskRepository(s).load_risk_state(tenant_id)

    assert state.open_positions_count == 3


# ---------------------------------------------------------------------------
# 3. Latest equity picks max created_at.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_latest_equity_picks_max_recorded_at(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Seed 5 snapshots; latest by created_at wins ``capital``."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-latest-equity")
    # Insert oldest first; offsets are seconds from now.
    for offset, equity in [
        (-500, Decimal("9000")),
        (-400, Decimal("9500")),
        (-300, Decimal("10500")),
        (-200, Decimal("11200")),
        (-50, Decimal("9800")),  # latest by offset.
    ]:
        await _seed_equity_snapshot(
            schema_session_factory,
            tenant_id=tenant_id,
            account_equity=equity,
            offset_seconds=offset,
        )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        state = await RiskRepository(s).load_risk_state(tenant_id)

    assert state.capital == Decimal("9800")


# ---------------------------------------------------------------------------
# 4. Peak equity picks MAX(equity).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_peak_equity_picks_max_equity(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Drawdown reflects ``MAX(equity)`` minus latest, divided by peak."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-peak-equity")
    # Peak = 12000 (offset -300); latest = 9000 (offset -50).
    for offset, equity in [
        (-500, Decimal("10000")),
        (-300, Decimal("12000")),  # peak.
        (-200, Decimal("11000")),
        (-50, Decimal("9000")),  # latest.
    ]:
        await _seed_equity_snapshot(
            schema_session_factory,
            tenant_id=tenant_id,
            account_equity=equity,
            offset_seconds=offset,
        )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        state = await RiskRepository(s).load_risk_state(tenant_id)

    # Peak query returns 12000 (not asserted directly — exercised via drawdown).
    assert state.capital == Decimal("9000")
    # Drawdown = (12000 - 9000) / 12000 = 0.25
    assert state.peak_to_trough_drawdown_pct == Decimal("0.25")


# ---------------------------------------------------------------------------
# 5. Drawdown computed from peak minus latest.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drawdown_computed_from_peak_minus_latest(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Explicit assertion: peak=12000, latest=9000 → drawdown = 0.25."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-drawdown")
    await _seed_equity_snapshot(
        schema_session_factory,
        tenant_id=tenant_id,
        account_equity=Decimal("12000"),
        offset_seconds=-300,
    )
    await _seed_equity_snapshot(
        schema_session_factory,
        tenant_id=tenant_id,
        account_equity=Decimal("9000"),
        offset_seconds=-30,
    )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        state = await RiskRepository(s).load_risk_state(tenant_id)

    assert state.peak_to_trough_drawdown_pct == Decimal("0.25")


# ---------------------------------------------------------------------------
# 6. Day loss pct sums today only.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_day_loss_pct_sums_today_only(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two trades today (-100, +50) + 1 yesterday (-200) → day_pnl = -50."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-day-loss")
    await _seed_equity_snapshot(
        schema_session_factory,
        tenant_id=tenant_id,
        account_equity=Decimal("10000"),
        offset_seconds=-10,
    )

    now = utc_now()
    today_start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    yesterday = today_start - timedelta(hours=2)

    # Trade closed today (-100).
    proposal_a = await _seed_proposal(schema_session_factory, tenant_id=tenant_id)
    # Trade closed today (+50).
    proposal_b = await _seed_proposal(schema_session_factory, tenant_id=tenant_id)
    # Trade closed yesterday (-200) — excluded.
    proposal_c = await _seed_proposal(schema_session_factory, tenant_id=tenant_id)

    today_a = today_start + timedelta(hours=1)
    today_b = today_start + timedelta(hours=2)

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        for pid, closed_at, pnl in [
            (proposal_a, today_a, Decimal("-100")),
            (proposal_b, today_b, Decimal("50")),
            (proposal_c, yesterday, Decimal("-200")),
        ]:
            s.add(
                Trade(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    proposal_id=pid,
                    symbol="SPY",
                    side="buy",
                    quantity=Decimal("10"),
                    mode="paper",
                    state="closed_filled",
                    opened_at=closed_at - timedelta(minutes=5),
                    closed_at=closed_at,
                    exit_reason="stop" if pnl < 0 else "target",
                    realised_pnl=pnl,
                )
            )
        await s.commit()

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        state = await RiskRepository(s).load_risk_state(tenant_id)

    # day_pnl = -100 + 50 = -50 → loss_pct = 50/10000 = 0.005
    assert state.day_to_date_loss_pct == Decimal("0.005")


# ---------------------------------------------------------------------------
# 7. Week loss pct sums since Monday.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_week_loss_pct_sums_since_monday(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Week starts Monday UTC; rows before it are excluded from week_pnl."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-week-loss")
    await _seed_equity_snapshot(
        schema_session_factory,
        tenant_id=tenant_id,
        account_equity=Decimal("10000"),
        offset_seconds=-10,
    )

    now = utc_now()
    today = now.date()
    week_start = datetime.combine(
        today - timedelta(days=today.weekday()),
        time.min,
        tzinfo=UTC,
    )
    last_week = week_start - timedelta(days=1)

    proposal_a = await _seed_proposal(schema_session_factory, tenant_id=tenant_id)
    proposal_b = await _seed_proposal(schema_session_factory, tenant_id=tenant_id)

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        # In-week loss of 300.
        s.add(
            Trade(
                id=uuid4(),
                tenant_id=tenant_id,
                proposal_id=proposal_a,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state="closed_filled",
                opened_at=week_start + timedelta(hours=1),
                closed_at=week_start + timedelta(hours=2),
                exit_reason="stop",
                realised_pnl=Decimal("-300"),
            )
        )
        # Last-week loss — excluded.
        s.add(
            Trade(
                id=uuid4(),
                tenant_id=tenant_id,
                proposal_id=proposal_b,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state="closed_filled",
                opened_at=last_week - timedelta(hours=2),
                closed_at=last_week - timedelta(hours=1),
                exit_reason="stop",
                realised_pnl=Decimal("-500"),
            )
        )
        await s.commit()

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        state = await RiskRepository(s).load_risk_state(tenant_id)

    # week_pnl = -300 → loss_pct = 300/10000 = 0.03
    assert state.week_to_date_loss_pct == Decimal("0.03")


# ---------------------------------------------------------------------------
# 8. Recent stoplosses count exit_reason == 'stop'.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_recent_stoplosses_counts_exit_reason_stop(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Seed 5 closed (3 stop, 1 target, 1 manual) → count == 3, lookback == 5."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-stoploss-guard")
    reasons = ["stop", "target", "stop", "manual", "stop"]
    # Insert oldest to newest so closed_at DESC ordering returns all 5.
    for idx, reason in enumerate(reasons):
        await _seed_trade(
            schema_session_factory,
            tenant_id=tenant_id,
            state="closed_filled",
            closed_offset_seconds=-(len(reasons) - idx) * 60,
            exit_reason=reason,
            realised_pnl=Decimal("-50") if reason == "stop" else Decimal("75"),
        )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        state = await RiskRepository(s).load_risk_state(tenant_id)

    assert state.recent_stoploss_count_trailing == 3
    assert state.recent_trades_lookback == 5


# ---------------------------------------------------------------------------
# 9. Seconds since last close per symbol.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_seconds_since_last_close_per_symbol_dict(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two symbols (SPY @ -600s, QQQ @ -300s) → both present with tolerance."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-cooldown")
    await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_id,
        symbol="SPY",
        state="closed_filled",
        closed_offset_seconds=-600,
        exit_reason="target",
        realised_pnl=Decimal("100"),
    )
    await _seed_trade(
        schema_session_factory,
        tenant_id=tenant_id,
        symbol="QQQ",
        state="closed_filled",
        closed_offset_seconds=-300,
        exit_reason="stop",
        realised_pnl=Decimal("-50"),
    )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        state = await RiskRepository(s).load_risk_state(tenant_id)

    dict_ = state.seconds_since_last_close_by_symbol
    assert set(dict_.keys()) == {"SPY", "QQQ"}
    # Allow a wide tolerance — utc_now() inside _seed_trade vs inside
    # load_risk_state are different calls and can drift by seconds on
    # slow CI runners.
    assert 580 <= dict_["SPY"] <= 660
    assert 280 <= dict_["QQQ"] <= 360


# ---------------------------------------------------------------------------
# 10. Tenant scoping — assertions don't leak across tenants.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_state_is_tenant_scoped(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Seed two tenants with different data; each load returns its own."""
    alice_id = await _seed_tenant(schema_session_factory, "t-alice")
    bob_id = await _seed_tenant(schema_session_factory, "t-bob")

    # Alice: 2 open trades + 1 stop loss.
    for _ in range(2):
        await _seed_trade(
            schema_session_factory,
            tenant_id=alice_id,
            state="open",
        )
    await _seed_trade(
        schema_session_factory,
        tenant_id=alice_id,
        state="closed_filled",
        closed_offset_seconds=-120,
        exit_reason="stop",
        realised_pnl=Decimal("-100"),
    )
    # Bob: 5 open trades + 0 closed.
    for _ in range(5):
        await _seed_trade(
            schema_session_factory,
            tenant_id=bob_id,
            state="open",
        )

    async with with_tenant_context(alice_id), schema_session_factory() as s:
        alice_state = await RiskRepository(s).load_risk_state(alice_id)
    async with with_tenant_context(bob_id), schema_session_factory() as s:
        bob_state = await RiskRepository(s).load_risk_state(bob_id)

    assert alice_state.open_positions_count == 2
    assert alice_state.recent_stoploss_count_trailing == 1
    assert alice_state.recent_trades_lookback == 1

    assert bob_state.open_positions_count == 5
    assert bob_state.recent_stoploss_count_trailing == 0
    assert bob_state.recent_trades_lookback == 0
    assert bob_state.seconds_since_last_close_by_symbol == {}
