"""Integration tests — order-placement timeout + startup reconciliation.

Slice ``order-timeout-restart-reconcile``. Covers:

1. ``execute_on_approval_handler`` bails with ``OrderRejected`` /
   ``reason="timeout"`` when ``broker.place_order`` hangs past the
   configured ``order_timeout_secs``.
2. ``close_trade`` raises ``TimeoutError`` when the exit-side
   placement hangs (the manual-close API surfaces it as a generic
   500 — operator retries; trade stays in ``state="open"``).
3. ``startup_reconcile`` computes a ``since`` boundary of
   ``max(filled_at) - safety_margin`` when fills exist.
4. ``startup_reconcile`` falls back to ``now - 24h`` when no fills
   are in the DB.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.trading.events import (
    OrderRejected,
    ProposalApproved,
)
from iguanatrader.contexts.trading.models import (
    Fill,
    Order,
    StrategyConfig,
    Trade,
    TradeProposal,
)
from iguanatrader.contexts.trading.ports import (
    BrokerOrderId,
    BrokerPort,
    EquitySnapshotValue,
    NewOrder,
    Position,
)
from iguanatrader.contexts.trading.service import TradingService
from iguanatrader.persistence import Tenant
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from iguanatrader.shared.messagebus import Event, MessageBus
from iguanatrader.shared.time import now as utc_now
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _HangingBroker(BrokerPort):
    """Broker whose ``place_order`` sleeps until the timeout fires.

    Constructed with ``hang_seconds`` longer than the service's
    timeout so the test deterministically triggers ``TimeoutError``.
    """

    def __init__(self, *, tenant_id: UUID, hang_seconds: float = 5.0) -> None:
        self._tenant_id = tenant_id
        self._hang_seconds = hang_seconds

    async def place_order(self, order: NewOrder) -> BrokerOrderId:
        await asyncio.sleep(self._hang_seconds)
        return BrokerOrderId("UNREACHABLE")

    async def cancel_order(self, broker_order_id: BrokerOrderId) -> None:  # pragma: no cover
        return None

    async def get_position(self, symbol: str) -> Position:  # pragma: no cover
        raise NotImplementedError

    async def list_positions(self) -> list[Position]:  # pragma: no cover
        return []

    async def get_account_equity(self) -> EquitySnapshotValue:
        return EquitySnapshotValue(
            tenant_id=self._tenant_id,
            mode="paper",
            account_equity=Decimal("10000"),
            cash_balance=Decimal("10000"),
            realized_pnl_today=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            currency="USD",
            snapshot_kind="event",
            captured_at=utc_now(),
        )

    async def reconcile_fills(self, since: datetime) -> Any:  # pragma: no cover
        if False:
            yield
        return


class _RecordingBus(MessageBus):
    def __init__(self) -> None:
        super().__init__()
        self.published: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.published.append(event)
        await super().publish(event)


async def _seed_tenant(sf: async_sessionmaker[AsyncSession], name: str) -> UUID:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=name, feature_flags={}))
        await s.commit()
    return tid


async def _seed_proposal(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
) -> tuple[UUID, UUID]:
    """Seed a strategy_config + an approved-ready trade proposal."""
    sc_id = uuid4()
    proposal_id = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            StrategyConfig(
                id=sc_id,
                tenant_id=tenant_id,
                strategy_kind="donchian_atr",
                symbol="SPY",
                params={"lookback": 20},
                enabled=True,
            )
        )
        await s.commit()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            TradeProposal(
                id=proposal_id,
                tenant_id=tenant_id,
                strategy_config_id=sc_id,
                research_brief_id=None,
                correlation_id=uuid4(),
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("100"),
                stop_price=Decimal("90"),
                reasoning={"why": "test"},
                mode="paper",
            )
        )
        await s.commit()
    return sc_id, proposal_id


def _stub_resolver() -> Any:
    """Resolver stub — never invoked in these tests.

    ``execute_on_approval_handler`` does not call the strategy
    resolver (it reads the proposal row directly). ``close_trade``
    and ``startup_reconcile`` also do not. We pass a stub that
    raises if called so a future flow change surfaces immediately.
    """

    async def _resolve(_sid: UUID) -> Any:
        raise AssertionError("strategy_resolver should not be called in these tests")

    return _resolve


@pytest.mark.asyncio
async def test_execute_on_approval_times_out_with_timeout_reason(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(schema_session_factory, "t-timeout")
    _sc_id, proposal_id = await _seed_proposal(schema_session_factory, tenant_id=tenant_id)

    broker = _HangingBroker(tenant_id=tenant_id, hang_seconds=2.0)
    bus = _RecordingBus()
    resolver = _stub_resolver()

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        service = TradingService(
            bus=bus,
            broker=broker,
            strategy_resolver=resolver,
            order_timeout_secs=0.2,  # 200 ms — much shorter than the 2s hang
        )
        await service.execute_on_approval_handler(
            ProposalApproved(tenant_id=tenant_id, proposal_id=proposal_id)
        )

    rejections = [e for e in bus.published if isinstance(e, OrderRejected)]
    assert len(rejections) == 1
    assert rejections[0].reason == "timeout"
    assert rejections[0].proposal_id == proposal_id


@pytest.mark.asyncio
async def test_close_trade_propagates_timeout_to_caller(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(schema_session_factory, "t-close-timeout")
    _sc_id, proposal_id = await _seed_proposal(schema_session_factory, tenant_id=tenant_id)

    trade_id = uuid4()
    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        s.add(
            Trade(
                id=trade_id,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state="open",
                opened_at=utc_now(),
            )
        )
        await s.commit()

    broker = _HangingBroker(tenant_id=tenant_id, hang_seconds=2.0)
    bus = _RecordingBus()
    resolver = _stub_resolver()

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        service = TradingService(
            bus=bus,
            broker=broker,
            strategy_resolver=resolver,
            order_timeout_secs=0.2,
        )
        with pytest.raises(TimeoutError):
            await service.close_trade(trade_id, reason="manual")


@pytest.mark.asyncio
async def test_startup_reconcile_uses_latest_filled_at_when_present(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(schema_session_factory, "t-reconcile")
    _sc_id, proposal_id = await _seed_proposal(schema_session_factory, tenant_id=tenant_id)

    trade_id = uuid4()
    order_id = uuid4()
    fill_id = uuid4()
    fill_at = utc_now() - timedelta(hours=2)

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        s.add(
            Trade(
                id=trade_id,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state="open",
                opened_at=fill_at - timedelta(minutes=1),
            )
        )
        await s.commit()

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        s.add(
            Order(
                id=order_id,
                tenant_id=tenant_id,
                trade_id=trade_id,
                broker="ibkr",
                broker_order_id="BR-1",
                order_type="market",
                side="buy",
                quantity=Decimal("10"),
                state="filled",
                submitted_at=fill_at - timedelta(seconds=10),
            )
        )
        await s.commit()

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        s.add(
            Fill(
                id=fill_id,
                tenant_id=tenant_id,
                order_id=order_id,
                quantity_filled=Decimal("10"),
                fill_price=Decimal("100"),
                commission=Decimal("1"),
                commission_currency="USD",
                filled_at=fill_at,
                broker_fill_id="F-1",
            )
        )
        await s.commit()

    captured_since: list[datetime] = []

    class _CaptureBroker(_HangingBroker):
        async def reconcile_fills(self, since: datetime) -> Any:
            captured_since.append(since)
            if False:
                yield
            return

    broker = _CaptureBroker(tenant_id=tenant_id, hang_seconds=0.0)
    bus = _RecordingBus()
    resolver = _stub_resolver()

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        service = TradingService(
            bus=bus,
            broker=broker,
            strategy_resolver=resolver,
        )
        await service.startup_reconcile(safety_margin_minutes=10)

    assert len(captured_since) == 1
    # SQLite drops tz info so the round-tripped latest_filled_at is
    # tz-naive while our fill_at is tz-aware. Coerce both to naive
    # UTC for the comparison.
    fill_at_naive = fill_at.replace(tzinfo=None)
    since_naive = (
        captured_since[0].replace(tzinfo=None) if captured_since[0].tzinfo else captured_since[0]
    )
    delta = fill_at_naive - since_naive
    # since == fill_at - 10 min; allow 1 s of clock drift
    assert timedelta(minutes=10) - timedelta(seconds=1) <= delta <= timedelta(minutes=10, seconds=1)


@pytest.mark.asyncio
async def test_startup_reconcile_falls_back_to_24h_window_when_db_empty(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(schema_session_factory, "t-reconcile-empty")

    captured_since: list[datetime] = []

    class _CaptureBroker(_HangingBroker):
        async def reconcile_fills(self, since: datetime) -> Any:
            captured_since.append(since)
            if False:
                yield
            return

    broker = _CaptureBroker(tenant_id=tenant_id, hang_seconds=0.0)
    bus = _RecordingBus()

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        service = TradingService(
            bus=bus,
            broker=broker,
            strategy_resolver=_stub_resolver(),
        )
        await service.startup_reconcile()

    assert len(captured_since) == 1
    # captured_since[0] is computed in production with utc_now() which
    # returns a tz-aware datetime; no SQLite round-trip here so no
    # tz coercion needed.
    age = utc_now() - captured_since[0]
    # Default fallback is 24h; allow 5s of drift
    assert timedelta(hours=24) - timedelta(seconds=5) <= age <= timedelta(hours=24, seconds=5)


@pytest.mark.asyncio
async def test_execute_on_approval_rejected_when_kill_switch_active(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """#5: a proposal approved around a kill-switch trip must NOT place a
    live order. The execute boundary re-reads the authoritative
    kill-switch state and publishes ``OrderRejected(reason="kill_switch")``
    without contacting the broker."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-killswitch")
    _sc_id, proposal_id = await _seed_proposal(schema_session_factory, tenant_id=tenant_id)

    placed: list[NewOrder] = []

    class _RecordingBroker(_HangingBroker):
        async def place_order(self, order: NewOrder) -> BrokerOrderId:
            placed.append(order)
            return BrokerOrderId("SHOULD-NOT-HAPPEN")

    broker = _RecordingBroker(tenant_id=tenant_id, hang_seconds=0.0)
    bus = _RecordingBus()

    async def _halted(_tid: UUID) -> bool:
        return True

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        service = TradingService(
            bus=bus,
            broker=broker,
            strategy_resolver=_stub_resolver(),
            kill_switch_reader=_halted,
        )
        await service.execute_on_approval_handler(
            ProposalApproved(tenant_id=tenant_id, proposal_id=proposal_id)
        )

    assert placed == []  # broker never contacted
    rejections = [e for e in bus.published if isinstance(e, OrderRejected)]
    assert len(rejections) == 1
    assert rejections[0].reason == "kill_switch"
    assert rejections[0].proposal_id == proposal_id


@pytest.mark.asyncio
async def test_execute_on_approval_generic_broker_error_is_caught(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """#8: a non-timeout/non-auth/non-budget broker error must not escape
    the handler (which pre-WS0 killed the bus worker). It yields a
    persisted rejected Order + ``OrderRejected(reason="broker_other")``."""
    from iguanatrader.shared.errors import IntegrationError

    tenant_id = await _seed_tenant(schema_session_factory, "t-broker-err")
    _sc_id, proposal_id = await _seed_proposal(schema_session_factory, tenant_id=tenant_id)

    class _ErroringBroker(_HangingBroker):
        async def place_order(self, order: NewOrder) -> BrokerOrderId:
            raise IntegrationError(detail="client not connected")

    broker = _ErroringBroker(tenant_id=tenant_id, hang_seconds=0.0)
    bus = _RecordingBus()

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        service = TradingService(
            bus=bus,
            broker=broker,
            strategy_resolver=_stub_resolver(),
        )
        # Must NOT raise out of the handler.
        await service.execute_on_approval_handler(
            ProposalApproved(tenant_id=tenant_id, proposal_id=proposal_id)
        )

    rejections = [e for e in bus.published if isinstance(e, OrderRejected)]
    assert len(rejections) == 1
    assert rejections[0].reason == "broker_other"
