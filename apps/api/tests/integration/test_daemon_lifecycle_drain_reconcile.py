"""Integration tests for :class:`DaemonLifecycleService` (slice
``dual-daemon-followups`` Phase-2.5 + Phase-6).

Covers the bigger flows the route-layer smoke pass (``test_daemon_routes_smoke``)
deliberately defers:

* **Drain**: toggle-off → ``_drain_pending_proposals`` → every
  ``pending_approval`` row for the daemon's mode lands at
  ``state='rejected'`` + ``rejection_reason='daemon_drained'``. Phase-6
  task 31 + 34.

* **Reconcile, positions in sync**: ``BrokerPort.list_positions`` matches
  the local open-trade set → no state changes. Phase-6 task 32 (positive
  branch).

* **Reconcile, broker dropped a position**: local trade for ``AAPL`` in
  ``state='open'``; broker reports no AAPL → trade closes with
  ``exit_reason='ibkr_reconcile'`` + ``state='closed'``. Phase-2.5
  acceptance + Phase-6 task 32 (negative branch).

Tests run against an in-memory SQLite engine + the shared
``register_global_listeners`` stack so the slice-3 tenant + append-only
listeners (whitelist update for the reconcile UPDATE) are exercised.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.trading.daemon_lifecycle import DaemonLifecycleService
from iguanatrader.contexts.trading.models import (
    EquitySnapshot,
    StrategyConfig,
    TenantTradingMode,
    Trade,
    TradeProposal,
)
from iguanatrader.contexts.trading.ports import (
    BrokerOrderId,
    EquitySnapshotValue,
    FillEvent,
    NewOrder,
    Position,
    WorkingOrder,
)
from iguanatrader.contexts.trading.repository import (
    EquitySnapshotRepository,
    TradeRepository,
    TradingModeRepository,
)

if TYPE_CHECKING:
    from iguanatrader.contexts.trading.ports import BrokerPort
    from iguanatrader.contexts.trading.service import TradingService
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from iguanatrader.shared.messagebus import MessageBus
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield None
    finally:
        unregister_global_listeners()


@pytest.fixture
async def session_maker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = engine_factory(url="sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = session_factory(engine)
    try:
        yield sf
    finally:
        await engine.dispose()


async def _seed_tenant(
    sf: async_sessionmaker[AsyncSession],
    *,
    mode_enabled: bool = True,
) -> UUID:
    """Seed a tenant + a (tenant, mode='paper') trading-mode row + a
    strategy_config so trades have a valid FK target.

    Tenants live outside the slice-3 tenant filter (``__tenant_scoped__
    = False``), so the cross-tenant INSERT runs without a context; the
    tenant-scoped child rows run inside ``with_tenant_context``.
    """
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=f"t{tid.hex[:8]}"))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            TenantTradingMode(
                tenant_id=tid,
                mode="paper",
                enabled=mode_enabled,
                last_toggled_at=datetime.now(UTC),
            )
        )
        s.add(
            StrategyConfig(
                id=uuid4(),
                tenant_id=tid,
                strategy_kind="donchian_atr",
                symbol="AAPL",
                params={"channel": 20},
                enabled=True,
                version=1,
            )
        )
        await s.commit()
    return tid


async def _seed_pending_proposal(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str = "AAPL",
    mode: str = "paper",
) -> UUID:
    """Insert a TradeProposal in ``state='pending_approval'`` for drain test."""
    async with sf() as s, with_tenant_context(tenant_id):
        # Resolve the strategy_config_id seeded by _seed_tenant.
        from sqlalchemy import select

        sc = (
            await s.execute(select(StrategyConfig.id).where(StrategyConfig.symbol == symbol))
        ).scalar_one()
        pid = uuid4()
        s.add(
            TradeProposal(
                id=pid,
                tenant_id=tenant_id,
                strategy_config_id=sc,
                symbol=symbol,
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("100"),
                stop_price=Decimal("95"),
                reasoning={"signal": "breakout"},
                mode=mode,
                correlation_id=uuid4(),
                state="pending_approval",
            )
        )
        await s.commit()
    return pid


async def _seed_open_trade(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    proposal_id: UUID,
    symbol: str,
    mode: str = "paper",
) -> UUID:
    """Insert a Trade in ``state='open'`` for reconcile test."""
    async with sf() as s, with_tenant_context(tenant_id):
        tid = uuid4()
        s.add(
            Trade(
                id=tid,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol=symbol,
                side="buy",
                quantity=Decimal("10"),
                mode=mode,
                state="open",
                opened_at=datetime.now(UTC),
            )
        )
        await s.commit()
    return tid


# ---------------------------------------------------------------------------
# Fake broker — implements BrokerPort.list_positions for the reconcile test
# ---------------------------------------------------------------------------


class _FakeBroker:
    """Minimal BrokerPort impl scoped to the reconcile path.

    ``positions`` is the set the broker reports on ``list_positions``.
    The rest of the BrokerPort surface raises so a misuse in the test
    surfaces loudly (NotImplementedError vs silent zero-rows).
    """

    def __init__(self, *, tenant_id: UUID, positions: list[Position]) -> None:
        self._tenant_id = tenant_id
        self._positions = positions

    async def place_order(self, order: NewOrder) -> BrokerOrderId:  # pragma: no cover
        raise NotImplementedError

    async def cancel_order(self, broker_order_id: BrokerOrderId) -> None:  # pragma: no cover
        raise NotImplementedError

    async def get_position(self, symbol: str) -> Position:  # pragma: no cover
        for p in self._positions:
            if p.symbol == symbol:
                return p
        return Position(
            tenant_id=self._tenant_id,
            symbol=symbol,
            quantity=Decimal("0"),
            average_price=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            currency="USD",
        )

    async def list_positions(self) -> list[Position]:
        return list(self._positions)

    async def list_working_orders(self) -> list[WorkingOrder]:
        return []

    async def get_account_equity(self) -> EquitySnapshotValue:
        return EquitySnapshotValue(
            tenant_id=self._tenant_id,
            mode="paper",
            account_equity=Decimal("10000"),
            cash_balance=Decimal("9000"),
            realized_pnl_today=Decimal("0"),
            unrealized_pnl=Decimal("100"),
            currency="USD",
            snapshot_kind="event",
            captured_at=datetime.now(UTC),
        )

    async def reconcile_fills(self, since: datetime) -> AsyncIterator[FillEvent]:
        if False:
            yield  # pragma: no cover
        return


class _FakeTradingService:
    """``startup_reconcile`` is the only method the lifecycle service
    calls on the trading service from the reconcile path."""

    async def startup_reconcile(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Drain — Phase-6 task 31 (integration) + task 34 (unit, same flow at
# different scope; one test exercises both)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_rejects_pending_proposals(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Toggle-off drain transitions every pending_approval row for the
    daemon's mode to ``state='rejected'`` + ``rejection_reason='daemon_drained'``.

    Idempotency: a second call updates 0 rows (already rejected).
    """
    tid = await _seed_tenant(session_maker)
    pid1 = await _seed_pending_proposal(session_maker, tenant_id=tid)
    pid2 = await _seed_pending_proposal(session_maker, tenant_id=tid)

    async with session_maker() as s, with_tenant_context(tid):
        session_var.set(s)
        service = DaemonLifecycleService(
            mode="paper",
            tenant_id=tid,
            bus=MessageBus(),
            trading_service=cast("TradingService", _FakeTradingService()),
            trading_mode_repo=TradingModeRepository(),
            broker=cast("BrokerPort", _FakeBroker(tenant_id=tid, positions=[])),
            equity_repo=EquitySnapshotRepository(),
            trade_repo=TradeRepository(),
        )
        first = await service._drain_pending_proposals(reason="daemon_drained")
        await s.commit()
        second = await service._drain_pending_proposals(reason="daemon_drained")
        await s.commit()

    assert first == 2
    assert second == 0

    async with session_maker() as s, with_tenant_context(tid):
        from sqlalchemy import select

        rows = (
            (await s.execute(select(TradeProposal).where(TradeProposal.id.in_([pid1, pid2]))))
            .scalars()
            .all()
        )

    assert {r.state for r in rows} == {"rejected"}
    assert {r.rejection_reason for r in rows} == {"daemon_drained"}
    assert all(r.rejected_at is not None for r in rows)


# ---------------------------------------------------------------------------
# Reconcile — Phase-2.5 + Phase-6 task 32
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_positions_in_sync_is_noop(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Broker reports the same symbols as the local open-trade set →
    no trades transition state."""
    tid = await _seed_tenant(session_maker)
    pid = await _seed_pending_proposal(session_maker, tenant_id=tid)
    trade_id = await _seed_open_trade(session_maker, tenant_id=tid, proposal_id=pid, symbol="AAPL")

    broker = _FakeBroker(
        tenant_id=tid,
        positions=[
            Position(
                tenant_id=tid,
                symbol="AAPL",
                quantity=Decimal("10"),
                average_price=Decimal("100"),
                unrealized_pnl=Decimal("0"),
                currency="USD",
            )
        ],
    )

    async with session_maker() as s, with_tenant_context(tid):
        session_var.set(s)
        service = DaemonLifecycleService(
            mode="paper",
            tenant_id=tid,
            bus=MessageBus(),
            trading_service=cast("TradingService", _FakeTradingService()),
            trading_mode_repo=TradingModeRepository(),
            broker=cast("BrokerPort", broker),
            equity_repo=EquitySnapshotRepository(),
            trade_repo=TradeRepository(),
        )
        await service._reconcile_positions(correlation_id=uuid4())
        await s.commit()

    async with session_maker() as s, with_tenant_context(tid):
        from sqlalchemy import select

        row = (await s.execute(select(Trade).where(Trade.id == trade_id))).scalar_one()
    assert row.state == "open"
    assert row.exit_reason is None
    assert row.closed_at is None


@pytest.mark.asyncio
async def test_reconcile_stamps_broker_marks_on_held_position(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A still-held broker position stamps ``avg_entry_price`` (avgCost) +
    ``unrealized_pnl`` + ``marks_updated_at`` on the matching local open trade
    (migration 0040).

    This is the ONLY reliable source for a position whose entry fills predate
    IBKR's reqExecutions window: the fills never reconcile, so the positions
    API would otherwise show "pendiente de ejecución" forever. The trade has
    zero fills here, mirroring the production INTC/MSFT/TSM/TXN rows.
    """
    tid = await _seed_tenant(session_maker)
    pid = await _seed_pending_proposal(session_maker, tenant_id=tid)
    trade_id = await _seed_open_trade(session_maker, tenant_id=tid, proposal_id=pid, symbol="AAPL")

    broker = _FakeBroker(
        tenant_id=tid,
        positions=[
            Position(
                tenant_id=tid,
                symbol="AAPL",
                quantity=Decimal("10"),
                average_price=Decimal("176.90"),
                unrealized_pnl=Decimal("42.50"),
                currency="USD",
            )
        ],
    )

    async with session_maker() as s, with_tenant_context(tid):
        session_var.set(s)
        service = DaemonLifecycleService(
            mode="paper",
            tenant_id=tid,
            bus=MessageBus(),
            trading_service=cast("TradingService", _FakeTradingService()),
            trading_mode_repo=TradingModeRepository(),
            broker=cast("BrokerPort", broker),
            equity_repo=EquitySnapshotRepository(),
            trade_repo=TradeRepository(),
        )
        await service._reconcile_positions(correlation_id=uuid4())
        await s.commit()

    async with session_maker() as s, with_tenant_context(tid):
        from sqlalchemy import select

        row = (await s.execute(select(Trade).where(Trade.id == trade_id))).scalar_one()
    # Marks stamped from the broker book — the append-only whitelist permitted
    # the UPDATE (regression guard for the L1/L2 lockstep). Narrow the
    # ``Mapped[Any | None]`` columns before constructing a Decimal.
    assert row.avg_entry_price is not None
    assert row.unrealized_pnl is not None
    assert row.marks_updated_at is not None
    assert Decimal(row.avg_entry_price) == Decimal("176.90")
    assert Decimal(row.unrealized_pnl) == Decimal("42.50")
    # Still open — marks do not transition state.
    assert row.state == "open"
    assert row.exit_reason is None


@pytest.mark.asyncio
async def test_reconcile_closes_orphan_local_trade(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Local trade has no broker counterpart → close with
    ``exit_reason='ibkr_reconcile'`` + ``state='closed'``."""
    tid = await _seed_tenant(session_maker)
    pid = await _seed_pending_proposal(session_maker, tenant_id=tid)
    trade_id = await _seed_open_trade(session_maker, tenant_id=tid, proposal_id=pid, symbol="AAPL")

    # Broker book is empty — AAPL was flat-closed by the operator while
    # the daemon was down.
    broker = _FakeBroker(tenant_id=tid, positions=[])

    async with session_maker() as s, with_tenant_context(tid):
        session_var.set(s)
        service = DaemonLifecycleService(
            mode="paper",
            tenant_id=tid,
            bus=MessageBus(),
            trading_service=cast("TradingService", _FakeTradingService()),
            trading_mode_repo=TradingModeRepository(),
            broker=cast("BrokerPort", broker),
            equity_repo=EquitySnapshotRepository(),
            trade_repo=TradeRepository(),
        )
        await service._reconcile_positions(correlation_id=uuid4())
        await s.commit()

    async with session_maker() as s, with_tenant_context(tid):
        from sqlalchemy import select

        row = (await s.execute(select(Trade).where(Trade.id == trade_id))).scalar_one()
    assert row.state == "closed"
    assert row.exit_reason == "ibkr_reconcile"
    assert row.closed_at is not None


@pytest.mark.asyncio
async def test_reconcile_with_ibkr_commits_orphan_close_durably(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Regression (#2/#27 in the reconcile path): the PUBLIC
    ``reconcile_with_ibkr`` must COMMIT its orphan-close + equity-snapshot
    writes at the unit-of-work boundary.

    The daemon runs on a long-lived session that nothing else commits, so a
    missing commit here logged ``positions_closed`` while the trade stayed
    ``open`` in the DB (observed in production). Unlike
    ``test_reconcile_closes_orphan_local_trade``, this drives the FULL public
    path and does NOT commit in the harness — committing in the test was
    exactly what masked the bug. Durability is asserted via a FRESH session.
    """
    tid = await _seed_tenant(session_maker)
    pid = await _seed_pending_proposal(session_maker, tenant_id=tid)
    trade_id = await _seed_open_trade(session_maker, tenant_id=tid, proposal_id=pid, symbol="AAPL")

    # Broker book empty — AAPL flat-closed broker-side while the daemon was down.
    broker = _FakeBroker(tenant_id=tid, positions=[])

    async with session_maker() as s, with_tenant_context(tid):
        session_var.set(s)
        service = DaemonLifecycleService(
            mode="paper",
            tenant_id=tid,
            bus=MessageBus(),
            trading_service=cast("TradingService", _FakeTradingService()),
            trading_mode_repo=TradingModeRepository(),
            broker=cast("BrokerPort", broker),
            equity_repo=EquitySnapshotRepository(),
            trade_repo=TradeRepository(),
        )
        # NO manual commit — the production path must commit itself.
        await service.reconcile_with_ibkr()

    async with session_maker() as s, with_tenant_context(tid):
        from sqlalchemy import select

        row = (await s.execute(select(Trade).where(Trade.id == trade_id))).scalar_one()
        equity_rows = (
            (await s.execute(select(EquitySnapshot).where(EquitySnapshot.tenant_id == tid)))
            .scalars()
            .all()
        )
    # Orphan-close persisted durably (the bug: this stayed "open").
    assert row.state == "closed"
    assert row.exit_reason == "ibkr_reconcile"
    assert row.closed_at is not None
    # The equity snapshot (reconcile step 2) also landed.
    assert len(equity_rows) >= 1
