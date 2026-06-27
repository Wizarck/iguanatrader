"""``IBKRAdapter.list_working_orders`` — slice ``position-review-broker-visibility``.

Locks the read-only translation of the IBKR open-order book into domain
:class:`WorkingOrder`s: the stop trigger (``auxPrice``) must surface as
:attr:`WorkingOrder.stop_price` (``lmtPrice`` is empty for a plain stop), and
terminal rows the broker may still echo (Filled / Cancelled) must be dropped.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from iguanatrader.contexts.trading.brokers.client_protocol import OpenOrder
from iguanatrader.contexts.trading.brokers.ibkr_adapter import IBKRAdapter
from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import IBKRBrokerageModel

from tests._fakes.ib_async_fake import FakeIBClient


def _open_order(
    *,
    symbol: str,
    action: str,
    order_type: str,
    status: str = "Submitted",
    limit_price: Decimal | None = None,
    aux_price: Decimal | None = None,
    order_ref: str | None = None,
) -> OpenOrder:
    return OpenOrder(
        perm_id=1,
        client_id=1,
        order_ref=order_ref,
        symbol=symbol,
        action=action,
        total_quantity=Decimal("10"),
        order_type=order_type,
        limit_price=limit_price,
        status=status,
        aux_price=aux_price,
    )


@pytest.mark.asyncio
async def test_list_working_orders_maps_aux_price_to_stop_price() -> None:
    fake = FakeIBClient()
    fake.open_orders = [
        _open_order(
            symbol="AAPL",
            action="SELL",
            order_type="STP",
            aux_price=Decimal("180.50"),
            order_ref="trade-1",
        ),
    ]
    adapter = IBKRAdapter(brokerage=IBKRBrokerageModel.for_paper(), client_factory=lambda: fake)
    await adapter.connect()
    try:
        orders = await adapter.list_working_orders()
    finally:
        await adapter.disconnect()

    assert len(orders) == 1
    stop = orders[0]
    assert stop.symbol == "AAPL"
    assert stop.action == "SELL"
    assert stop.order_type == "STP"
    # The stop TRIGGER (auxPrice) is surfaced as stop_price; limit_price stays None.
    assert stop.stop_price == Decimal("180.50")
    assert stop.limit_price is None
    assert stop.order_ref == "trade-1"


@pytest.mark.asyncio
async def test_list_working_orders_keeps_limit_for_take_profit() -> None:
    fake = FakeIBClient()
    fake.open_orders = [
        _open_order(symbol="MSFT", action="SELL", order_type="LMT", limit_price=Decimal("420")),
    ]
    adapter = IBKRAdapter(brokerage=IBKRBrokerageModel.for_paper(), client_factory=lambda: fake)
    await adapter.connect()
    try:
        orders = await adapter.list_working_orders()
    finally:
        await adapter.disconnect()

    assert len(orders) == 1
    assert orders[0].limit_price == Decimal("420")
    assert orders[0].stop_price is None


@pytest.mark.asyncio
async def test_list_working_orders_drops_terminal_statuses() -> None:
    fake = FakeIBClient()
    fake.open_orders = [
        _open_order(symbol="AAPL", action="SELL", order_type="STP", status="Submitted"),
        _open_order(symbol="AAPL", action="SELL", order_type="STP", status="Filled"),
        _open_order(symbol="AAPL", action="SELL", order_type="LMT", status="Cancelled"),
        _open_order(symbol="AAPL", action="SELL", order_type="STP", status="Inactive"),
    ]
    adapter = IBKRAdapter(brokerage=IBKRBrokerageModel.for_paper(), client_factory=lambda: fake)
    await adapter.connect()
    try:
        orders = await adapter.list_working_orders()
    finally:
        await adapter.disconnect()

    # Only the one "Submitted" working order survives.
    assert len(orders) == 1
    assert orders[0].status == "Submitted"
