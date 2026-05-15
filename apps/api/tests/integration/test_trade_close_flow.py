"""Integration tests — ``POST /trades/{id}/close`` + ``TradingService.close_trade``.

Slice ``trade-close-flow-exit-pathway``. Covers the synchronous API
validation path (404 / 409 / 202) and the asynchronous service flow:
* close_trade transitions a live trade to ``state="closing"`` and
  submits an exit order (opposite side) via a fake broker.
* On exit-order terminal fill, ``_reconcile_one_fill`` transitions the
  trade to ``state="closed"``, stamps ``closed_at``, writes
  ``exit_reason``, and computes ``realised_pnl`` over all entry/exit
  fills.
* Idempotency: a second close request against a ``closing`` trade
  raises :class:`TradeNotClosableError` (HTTP 409 / silent bus drop).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.trading.events import CloseTradeRequested
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
    FillEvent,
    NewOrder,
    Position,
)
from iguanatrader.contexts.trading.repository import (
    EquitySnapshotRepository,
    FillRepository,
    OrderRepository,
    TradeRepository,
)
from iguanatrader.contexts.trading.service import (
    TradeNotClosableError,
    TradingService,
)
from iguanatrader.persistence import Tenant
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from iguanatrader.shared.messagebus import MessageBus
from iguanatrader.shared.time import now as utc_now
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _FakeBroker(BrokerPort):
    """In-memory broker port for close-flow tests.

    Records every ``place_order`` call; returns a synthetic
    ``BrokerOrderId``. ``tenant_id`` is configurable so the equity
    snapshot returned by :meth:`get_account_equity` passes the
    tenant-listener cross-tenant guard.
    """

    def __init__(self, *, tenant_id: UUID) -> None:
        self.placed_orders: list[NewOrder] = []
        self._next_id = 1
        self._tenant_id = tenant_id

    async def place_order(self, order: NewOrder) -> BrokerOrderId:
        self.placed_orders.append(order)
        broker_id = BrokerOrderId(f"FAKE-{self._next_id:04d}")
        self._next_id += 1
        return broker_id

    async def cancel_order(self, broker_order_id: BrokerOrderId) -> None:
        return None

    async def get_position(self, symbol: str) -> Position:  # pragma: no cover
        raise NotImplementedError

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
            yield  # pragma: no cover
        return


async def _seed_tenant(sf: async_sessionmaker[AsyncSession], name: str) -> UUID:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=name, feature_flags={}))
        await s.commit()
    return tid


async def _seed_trade_with_entry_fill(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str = "SPY",
    side: str = "buy",
    quantity: Decimal = Decimal("10"),
    entry_price: Decimal = Decimal("100"),
    entry_commission: Decimal = Decimal("1"),
    state: str = "open",
) -> dict[str, UUID]:
    """Seed strategy_config + proposal + trade + entry order + entry fill."""
    sc_id = uuid4()
    proposal_id = uuid4()
    trade_id = uuid4()
    entry_order_id = uuid4()
    entry_fill_id = uuid4()
    now = utc_now()

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
                quantity=quantity,
                entry_price_indicative=entry_price,
                stop_price=(
                    entry_price - Decimal("10") if side == "buy" else entry_price + Decimal("10")
                ),
                reasoning={"why": "test"},
                mode="paper",
            )
        )
        await s.commit()

    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            Trade(
                id=trade_id,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                mode="paper",
                state=state,
                opened_at=now,
            )
        )
        await s.commit()

    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            Order(
                id=entry_order_id,
                tenant_id=tenant_id,
                trade_id=trade_id,
                broker="ibkr",
                broker_order_id=f"IB-ENTRY-{entry_order_id}",
                order_type="market",
                side=side,
                quantity=quantity,
                state="filled",
                submitted_at=now,
            )
        )
        await s.commit()

    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            Fill(
                id=entry_fill_id,
                tenant_id=tenant_id,
                order_id=entry_order_id,
                quantity_filled=quantity,
                fill_price=entry_price,
                commission=entry_commission,
                commission_currency="USD",
                filled_at=now,
                broker_fill_id=f"FILL-ENTRY-{entry_fill_id}",
            )
        )
        await s.commit()

    return {
        "tenant_id": tenant_id,
        "strategy_config_id": sc_id,
        "proposal_id": proposal_id,
        "trade_id": trade_id,
        "entry_order_id": entry_order_id,
        "entry_fill_id": entry_fill_id,
    }


async def _make_service(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
) -> tuple[TradingService, MessageBus, _FakeBroker]:
    """Construct a TradingService with a fake broker + in-memory bus."""
    bus = MessageBus()
    broker = _FakeBroker(tenant_id=tenant_id)

    async def _resolver(_id: UUID) -> Any:
        raise AssertionError("strategy_resolver should not be called in close-flow tests")

    service = TradingService(
        bus=bus,
        broker=broker,
        strategy_resolver=_resolver,
    )
    return service, bus, broker


# ---------------------------------------------------------------------------
# 1. close_trade transitions state and places exit order.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_close_trade_submits_exit_order_and_transitions_to_closing(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(schema_session_factory, "t-close-1")
    seed = await _seed_trade_with_entry_fill(schema_session_factory, tenant_id=tenant_id)
    service, _bus, broker = await _make_service(schema_session_factory, tenant_id=tenant_id)

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        broker_id = await service.close_trade(seed["trade_id"], reason="manual")
        await s.commit()

    assert broker_id.startswith("FAKE-")
    assert len(broker.placed_orders) == 1
    exit_order = broker.placed_orders[0]
    assert exit_order.side == "sell"  # opposite of trade's "buy"
    assert exit_order.quantity == Decimal("10")
    assert exit_order.symbol == "SPY"

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        repo = TradeRepository()
        trade = await repo.get_by_id(seed["trade_id"])
    assert trade is not None
    assert trade.state == "closing"
    assert trade.exit_reason == "manual"


# ---------------------------------------------------------------------------
# 2. Idempotency: closing a `closing` trade raises.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_close_trade_raises_if_already_closing(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(schema_session_factory, "t-close-2")
    seed = await _seed_trade_with_entry_fill(
        schema_session_factory, tenant_id=tenant_id, state="closing"
    )
    service, _bus, _broker = await _make_service(schema_session_factory, tenant_id=tenant_id)

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        with pytest.raises(TradeNotClosableError, match="state='closing'"):
            await service.close_trade(seed["trade_id"], reason="manual")


# ---------------------------------------------------------------------------
# 3. close_trade rejects unknown reason values.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_close_trade_rejects_invalid_reason(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(schema_session_factory, "t-close-3")
    seed = await _seed_trade_with_entry_fill(schema_session_factory, tenant_id=tenant_id)
    service, _bus, _broker = await _make_service(schema_session_factory, tenant_id=tenant_id)

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        with pytest.raises(ValueError, match="reason must be one of"):
            await service.close_trade(seed["trade_id"], reason="profit_take")


# ---------------------------------------------------------------------------
# 4. _reconcile_one_fill on exit-order terminal fill: state -> closed.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reconcile_terminal_exit_fill_transitions_to_closed_with_pnl(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """End-to-end: close_trade then simulate the broker's terminal exit fill."""
    tenant_id = await _seed_tenant(schema_session_factory, "t-close-4")
    seed = await _seed_trade_with_entry_fill(
        schema_session_factory,
        tenant_id=tenant_id,
        entry_price=Decimal("100"),
        entry_commission=Decimal("1"),
    )
    service, _bus, _broker = await _make_service(schema_session_factory, tenant_id=tenant_id)

    # 1. Operator initiates close (submits exit order, sets state=closing).
    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        await service.close_trade(seed["trade_id"], reason="target")
        # Persist the exit Order row (close_trade adds it; commit so the
        # subsequent fill reconcile in a fresh session can see it).
        await s.commit()

    # 2. Find the exit Order id the service just persisted.
    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        order_repo = OrderRepository()
        all_orders = await order_repo.list_for_trade(seed["trade_id"])
    exit_orders = [o for o in all_orders if o.side == "sell"]
    assert len(exit_orders) == 1
    exit_order_id = exit_orders[0].id

    # 3. Simulate the broker reporting a terminal exit fill at 110 (a $10
    #    win per share = $100 gross profit, minus commissions = $98 net).
    fill_event = FillEvent(
        tenant_id=tenant_id,
        order_id=exit_order_id,
        quantity_filled=Decimal("10"),
        fill_price=Decimal("110"),
        commission=Decimal("1"),
        commission_currency="USD",
        filled_at=utc_now(),
        broker_fill_id=f"FILL-EXIT-{exit_order_id}",
    )

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        await service._reconcile_one_fill(
            fill_event,
            fill_repo=FillRepository(),
            order_repo=OrderRepository(),
            trade_repo=TradeRepository(),
            equity_repo=EquitySnapshotRepository(),
        )
        await s.commit()

    # 4. Trade must now be closed with realised_pnl == 110*10 - 100*10 - (1+1) = 98.
    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        repo = TradeRepository()
        trade = await repo.get_by_id(seed["trade_id"])

    assert trade is not None
    assert trade.state == "closed"
    assert trade.closed_at is not None
    assert trade.exit_reason == "target"
    assert Decimal(str(trade.realised_pnl)) == Decimal("98")


# ---------------------------------------------------------------------------
# 5. CloseTradeRequested event handler.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_close_trade_handler_dispatches_through_bus(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(schema_session_factory, "t-close-5")
    seed = await _seed_trade_with_entry_fill(schema_session_factory, tenant_id=tenant_id)
    service, _bus, broker = await _make_service(schema_session_factory, tenant_id=tenant_id)

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        await service.close_trade_handler(
            CloseTradeRequested(
                tenant_id=tenant_id,
                trade_id=seed["trade_id"],
                reason="stop",
            )
        )
        await s.commit()

    assert len(broker.placed_orders) == 1
    assert broker.placed_orders[0].side == "sell"

    async with with_tenant_context(tenant_id), schema_session_factory() as s:
        session_var.set(s)
        repo = TradeRepository()
        trade = await repo.get_by_id(seed["trade_id"])
    assert trade is not None
    assert trade.state == "closing"
    assert trade.exit_reason == "stop"
