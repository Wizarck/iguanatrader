"""Unit tests for :class:`IbAsyncIBClient` shim (slice deployment-foundation §3.B).

The ``ib_async`` SDK is mocked via ``sys.modules`` so the shim's lazy
imports resolve to test doubles. Coverage is intentionally narrow —
the shim is a thin translator and the value-object converters are the
risky surface (numeric / string field shapes vary across ``ib_async``
versions). The higher-level lifecycle behaviour (HeartbeatMixin,
idempotency) is exercised by ``test_ibkr_adapter_lifecycle.py``
and is out of scope here.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def fake_ib_async_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Inject a fake ``ib_async`` module so the shim's lazy imports resolve."""
    module = ModuleType("ib_async")

    class _MarketOrder:
        def __init__(self, action: str, qty: float) -> None:
            self.action = action
            self.totalQuantity = qty
            self.orderType = "MKT"
            self.lmtPrice = 0.0
            self.auxPrice = 0.0
            self.transmit = True
            self.account = None
            self.orderRef = None

    class _LimitOrder(_MarketOrder):
        def __init__(self, action: str, qty: float, limit: float) -> None:
            super().__init__(action, qty)
            self.orderType = "LMT"
            self.lmtPrice = limit

    class _StopOrder(_MarketOrder):
        def __init__(self, action: str, qty: float, stop: float) -> None:
            super().__init__(action, qty)
            self.orderType = "STP"
            self.auxPrice = stop

    class _StopLimitOrder(_MarketOrder):
        def __init__(self, action: str, qty: float, limit: float, stop: float) -> None:
            super().__init__(action, qty)
            self.orderType = "STP LMT"
            self.lmtPrice = limit
            self.auxPrice = stop

    class _Stock:
        def __init__(self, symbol: str, exchange: str, currency: str) -> None:
            self.symbol = symbol
            self.exchange = exchange
            self.currency = currency

    class _ExecutionFilter:
        def __init__(self) -> None:
            self.time = ""

    class _IB:
        pass

    module.IB = _IB  # type: ignore[attr-defined]
    module.Stock = _Stock  # type: ignore[attr-defined]
    module.MarketOrder = _MarketOrder  # type: ignore[attr-defined]
    module.LimitOrder = _LimitOrder  # type: ignore[attr-defined]
    module.StopOrder = _StopOrder  # type: ignore[attr-defined]
    module.StopLimitOrder = _StopLimitOrder  # type: ignore[attr-defined]
    module.ExecutionFilter = _ExecutionFilter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ib_async", module)
    return module


@pytest.fixture
def adapter() -> "object":
    from iguanatrader.contexts.trading.brokers.ib_async_client import IbAsyncIBClient

    ib = MagicMock()
    ib.connectAsync = AsyncMock(return_value=None)
    ib.isConnected = MagicMock(return_value=True)
    ib.disconnect = MagicMock()
    ib.reqCurrentTimeAsync = AsyncMock(return_value=datetime(2026, 5, 7, 10, 0, tzinfo=UTC))
    return IbAsyncIBClient(ib=ib)


@pytest.mark.asyncio
async def test_connect_async_delegates_to_sdk(adapter: object) -> None:
    await adapter.connect_async("127.0.0.1", 7497, 1)  # type: ignore[attr-defined]
    adapter._ib.connectAsync.assert_awaited_once_with(  # type: ignore[attr-defined]
        host="127.0.0.1", port=7497, clientId=1
    )


def test_disconnect_calls_sdk_when_connected(adapter: object) -> None:
    adapter.disconnect()  # type: ignore[attr-defined]
    adapter._ib.disconnect.assert_called_once()  # type: ignore[attr-defined]


def test_disconnect_is_noop_when_not_connected(adapter: object) -> None:
    adapter._ib.isConnected = MagicMock(return_value=False)  # type: ignore[attr-defined]
    adapter.disconnect()  # type: ignore[attr-defined]
    adapter._ib.disconnect.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_req_current_time_returns_datetime(adapter: object) -> None:
    result = await adapter.req_current_time()  # type: ignore[attr-defined]
    assert result == datetime(2026, 5, 7, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_positions_translates_sdk_objects(adapter: object) -> None:
    sdk_position = SimpleNamespace(
        account="DU123",
        contract=SimpleNamespace(symbol="AAPL", currency="USD"),
        position=100,
        avgCost=150.5,
        unrealizedPNL=10.0,
    )
    adapter._ib.reqPositionsAsync = AsyncMock(return_value=[sdk_position])  # type: ignore[attr-defined]

    rows = list(await adapter.positions())  # type: ignore[attr-defined]

    assert len(rows) == 1
    assert rows[0].account == "DU123"
    assert rows[0].symbol == "AAPL"
    assert rows[0].quantity == Decimal("100")
    assert rows[0].average_cost == Decimal("150.5")
    assert rows[0].unrealized_pnl == Decimal("10.0")


@pytest.mark.asyncio
async def test_account_summary_translates_sdk_rows(adapter: object) -> None:
    sdk_row = SimpleNamespace(
        account="DU123",
        tag="NetLiquidation",
        value="100000.50",
        currency="USD",
    )
    adapter._ib.accountSummaryAsync = AsyncMock(return_value=[sdk_row])  # type: ignore[attr-defined]

    rows = list(await adapter.account_summary())  # type: ignore[attr-defined]

    assert len(rows) == 1
    assert rows[0].tag == "NetLiquidation"
    assert rows[0].value == Decimal("100000.50")


def test_value_object_translators_handle_lmt_order() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(
        action="BUY",
        total_quantity=Decimal("10"),
        order_type="LMT",
        limit_price=Decimal("123.45"),
        order_ref="my-client-order-id",
    )
    sdk_order = _to_order(order)

    assert sdk_order.action == "BUY"
    assert sdk_order.totalQuantity == 10.0
    assert sdk_order.orderType == "LMT"
    assert sdk_order.lmtPrice == 123.45
    assert sdk_order.orderRef == "my-client-order-id"


def test_value_object_translator_rejects_lmt_without_price() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    bad = IBOrder(action="BUY", total_quantity=Decimal("1"), order_type="LMT")
    with pytest.raises(ValueError, match="LMT order requires limit_price"):
        _to_order(bad)


def test_value_object_translator_rejects_unsupported_sec_type() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import Contract
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_contract

    bad = Contract(symbol="ES", sec_type="FUT")
    with pytest.raises(NotImplementedError, match="sec_type='FUT'"):
        _to_contract(bad)
