"""Integration test — :class:`ReplayService` end-to-end.

Seeds tenant + strategy_config + trade_proposals + a partially-
realized trade history. Wires an in-memory MarketDataAdapter with
synthetic bars surrounding each proposal's ``created_at``. Asserts:

1. Every seeded proposal appears in the result rows.
2. Each row has a SimulatedOutcome per policy.
3. Aggregates correctly count win-rate and exit reasons.
4. GateCalibration emits one block per policy with the right counters.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.replay.models import (
    DEFAULT_POLICIES,
    ExitPolicy,
)
from iguanatrader.contexts.replay.service import ReplayService
from iguanatrader.contexts.trading.market_data.in_memory import (
    InMemoryMarketDataAdapter,
)
from iguanatrader.contexts.trading.models import (
    StrategyConfig,
    Trade,
    TradeProposal,
)
from iguanatrader.contexts.trading.ports import Bar
from iguanatrader.persistence import Tenant
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _bar(
    ts: datetime,
    *,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
) -> Bar:
    return Bar(
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=Decimal("1000"),
    )


def _flat_series(start: datetime, days: int, price: Decimal) -> list[Bar]:
    return [
        _bar(
            start + timedelta(days=i),
            open_=price,
            high=price + Decimal("1"),
            low=price - Decimal("1"),
            close=price,
        )
        for i in range(days)
    ]


async def _seed_tenant(sf: async_sessionmaker[AsyncSession], name: str) -> UUID:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=name, feature_flags={}))
        await s.commit()
    return tid


async def _seed_strategy_config(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str = "AAPL",
) -> UUID:
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


async def _seed_proposal(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    strategy_config_id: UUID,
    created_at: datetime,
    symbol: str = "AAPL",
    side: str = "buy",
    entry_price: Decimal = Decimal("100"),
    stop_price: Decimal = Decimal("95"),
    quantity: Decimal = Decimal("10"),
) -> UUID:
    pid = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            TradeProposal(
                id=pid,
                tenant_id=tenant_id,
                strategy_config_id=strategy_config_id,
                research_brief_id=None,
                correlation_id=uuid4(),
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price_indicative=entry_price,
                stop_price=stop_price,
                reasoning={"why": "test"},
                mode="paper",
                created_at=created_at,
            )
        )
        await s.commit()
    return pid


async def _seed_trade_for_proposal(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    proposal_id: UUID,
    state: str,
    realised_pnl: Decimal | None,
    symbol: str = "AAPL",
    side: str = "buy",
    quantity: Decimal = Decimal("10"),
) -> UUID:
    tid = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            Trade(
                id=tid,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                mode="paper",
                state=state,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                realised_pnl=realised_pnl,
            )
        )
        await s.commit()
    return tid


@pytest.mark.asyncio
async def test_replay_window_evaluates_every_seeded_proposal(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(schema_session_factory, "t-replay")
    sc_id = await _seed_strategy_config(schema_session_factory, tenant_id=tenant_id)

    base = datetime(2026, 1, 1, tzinfo=UTC)
    # 3 proposals, each one week apart
    proposals: list[tuple[UUID, datetime]] = []
    for i in range(3):
        opened = base + timedelta(days=i * 7)
        pid = await _seed_proposal(
            schema_session_factory,
            tenant_id=tenant_id,
            strategy_config_id=sc_id,
            created_at=opened,
        )
        proposals.append((pid, opened))

    # 60 days of flat-ish bars covering the whole window
    bars = _flat_series(base - timedelta(days=15), 60, Decimal("100"))
    market_data_port = InMemoryMarketDataAdapter(seed={"AAPL": bars})

    async with schema_session_factory() as s:
        session_var.set(s)
        service = ReplayService(session=s, market_data_port=market_data_port)
        async with with_tenant_context(tenant_id):
            result = await service.replay_window(
                window_start=base - timedelta(days=1),
                window_end=base + timedelta(days=30),
                policies=DEFAULT_POLICIES,
            )

    assert len(result.rows) == 3
    assert result.proposals_skipped_no_bars == 0
    for row in result.rows:
        assert set(row.sim_outcomes.keys()) == {p.name for p in DEFAULT_POLICIES}


@pytest.mark.asyncio
async def test_replay_aggregates_count_winners_correctly(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(schema_session_factory, "t-replay-agg")
    sc_id = await _seed_strategy_config(schema_session_factory, tenant_id=tenant_id)

    base = datetime(2026, 1, 1, tzinfo=UTC)
    proposal_a = await _seed_proposal(
        schema_session_factory,
        tenant_id=tenant_id,
        strategy_config_id=sc_id,
        created_at=base,
    )
    _ = proposal_a

    # Bars that breach stop on day 2 → stop exit, negative PnL
    bars = [
        _bar(
            base - timedelta(days=10),
            open_=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
        ),
        # post-entry: day 1 flat, day 2 breaches stop
        _bar(
            base + timedelta(days=1),
            open_=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
        ),
        _bar(
            base + timedelta(days=2),
            open_=Decimal("99"),
            high=Decimal("99"),
            low=Decimal("90"),
            close=Decimal("92"),
        ),
    ]
    market_data_port = InMemoryMarketDataAdapter(seed={"AAPL": bars})

    async with schema_session_factory() as s:
        session_var.set(s)
        service = ReplayService(session=s, market_data_port=market_data_port)
        async with with_tenant_context(tenant_id):
            result = await service.replay_window(
                window_start=base - timedelta(days=1),
                window_end=base + timedelta(days=30),
                policies=(ExitPolicy(name="stop-only-30d"),),
            )

    assert len(result.aggregates) == 1
    agg = result.aggregates[0]
    assert agg.proposals_evaluated == 1
    assert agg.proposals_exited == 1
    # PnL = (95 - 100) * 10 = -50 (stop at 95, side buy, qty 10)
    assert agg.total_pnl == Decimal("-50")
    assert agg.win_rate == Decimal("0")
    assert agg.stop_rate == Decimal("1")


@pytest.mark.asyncio
async def test_replay_gate_calibration_distinguishes_approved_from_rejected(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(schema_session_factory, "t-replay-cal")
    sc_id = await _seed_strategy_config(schema_session_factory, tenant_id=tenant_id)

    base = datetime(2026, 1, 1, tzinfo=UTC)
    # Approved + profitable
    approved_pid = await _seed_proposal(
        schema_session_factory,
        tenant_id=tenant_id,
        strategy_config_id=sc_id,
        created_at=base,
    )
    await _seed_trade_for_proposal(
        schema_session_factory,
        tenant_id=tenant_id,
        proposal_id=approved_pid,
        state="closed",
        realised_pnl=Decimal("80"),
    )
    # Rejected (no Trade row) — would have been a winner per sim
    await _seed_proposal(
        schema_session_factory,
        tenant_id=tenant_id,
        strategy_config_id=sc_id,
        created_at=base + timedelta(days=1),
    )

    # Bars: post-entry move from 100 → 108 cleanly within horizon.
    bars = [
        _bar(
            base - timedelta(days=10),
            open_=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
        ),
        _bar(
            base + timedelta(days=1),
            open_=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("99"),
            close=Decimal("104"),
        ),
        _bar(
            base + timedelta(days=2),
            open_=Decimal("104"),
            high=Decimal("108"),
            low=Decimal("103"),
            close=Decimal("108"),
        ),
        _bar(
            base + timedelta(days=3),
            open_=Decimal("108"),
            high=Decimal("110"),
            low=Decimal("106"),
            close=Decimal("109"),
        ),
    ]
    market_data_port = InMemoryMarketDataAdapter(seed={"AAPL": bars})

    async with schema_session_factory() as s:
        session_var.set(s)
        service = ReplayService(session=s, market_data_port=market_data_port)
        async with with_tenant_context(tenant_id):
            result = await service.replay_window(
                window_start=base - timedelta(days=1),
                window_end=base + timedelta(days=30),
                policies=(ExitPolicy(name="stop-only-30d"),),
            )

    calibration = result.gate_calibrations[0]
    assert calibration.policy_name == "stop-only-30d"
    assert calibration.historical_approved_count == 1
    assert calibration.historical_approved_profitable_count == 1
    assert calibration.historical_rejected_count == 1
    # Whether the rejected one would have profited depends on the sim
    # outcome; we just assert the bookkeeping is internally consistent.
    assert calibration.gate_precision == Decimal("1")
