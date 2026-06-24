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
            self.sec_type = "STK"

    class _Future:
        def __init__(self, **kwargs: object) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)
            self.sec_type = "FUT"

    class _Option:
        def __init__(self, **kwargs: object) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)
            self.sec_type = "OPT"

    class _Forex:
        def __init__(self, pair: str) -> None:
            self.pair = pair
            self.sec_type = "CASH"

    class _Crypto:
        def __init__(self, symbol: str, exchange: str, currency: str) -> None:
            self.symbol = symbol
            self.exchange = exchange
            self.currency = currency
            self.sec_type = "CRYPTO"

    class _CFD:
        def __init__(self, symbol: str, exchange: str, currency: str) -> None:
            self.symbol = symbol
            self.exchange = exchange
            self.currency = currency
            self.sec_type = "CFD"

    class _Index:
        def __init__(self, symbol: str, exchange: str, currency: str) -> None:
            self.symbol = symbol
            self.exchange = exchange
            self.currency = currency
            self.sec_type = "IND"

    class _Order:
        """Base ``ib_async.Order`` — used for TRAIL / MOC / LOC paths."""

        def __init__(
            self,
            action: str = "",
            totalQuantity: float = 0.0,
            orderType: str = "",
        ) -> None:
            self.action = action
            self.totalQuantity = totalQuantity
            self.orderType = orderType
            self.lmtPrice = 0.0
            self.auxPrice = 0.0
            self.trailingPercent = 0.0
            self.lmtPriceOffset = 0.0
            self.transmit = True
            self.account = None
            self.orderRef = None

    class _ExecutionFilter:
        def __init__(self) -> None:
            self.time = ""

    class _IB:
        pass

    class _TagValue:
        """Minimal stand-in for ``ib_async.TagValue`` (algo param tuple)."""

        def __init__(self, tag: str, value: str) -> None:
            self.tag = tag
            self.value = value

        def __eq__(self, other: object) -> bool:
            return (
                isinstance(other, _TagValue) and self.tag == other.tag and self.value == other.value
            )

        def __repr__(self) -> str:
            return f"TagValue({self.tag!r}, {self.value!r})"

    module.IB = _IB  # type: ignore[attr-defined]
    module.Stock = _Stock  # type: ignore[attr-defined]
    module.Future = _Future  # type: ignore[attr-defined]
    module.Option = _Option  # type: ignore[attr-defined]
    module.Forex = _Forex  # type: ignore[attr-defined]
    module.Crypto = _Crypto  # type: ignore[attr-defined]
    module.CFD = _CFD  # type: ignore[attr-defined]
    module.Index = _Index  # type: ignore[attr-defined]
    module.Order = _Order  # type: ignore[attr-defined]
    module.MarketOrder = _MarketOrder  # type: ignore[attr-defined]
    module.LimitOrder = _LimitOrder  # type: ignore[attr-defined]
    module.StopOrder = _StopOrder  # type: ignore[attr-defined]
    module.StopLimitOrder = _StopLimitOrder  # type: ignore[attr-defined]
    module.ExecutionFilter = _ExecutionFilter  # type: ignore[attr-defined]
    module.TagValue = _TagValue  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ib_async", module)
    return module


@pytest.fixture
def adapter() -> object:
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


@pytest.mark.asyncio
async def test_account_summary_coerces_non_numeric_tags_to_zero(adapter: object) -> None:
    # Regression: IBKR returns string tags (AccountType, Currency, ...)
    # alongside the numeric ones. Decimal("INDIVIDUAL") used to raise
    # ConversionSyntax and fail the whole equity reconcile.
    sdk_rows = [
        SimpleNamespace(account="DU123", tag="NetLiquidation", value="100000.50", currency="USD"),
        SimpleNamespace(account="DU123", tag="AccountType", value="INDIVIDUAL", currency="USD"),
        SimpleNamespace(account="DU123", tag="Currency", value="USD", currency="USD"),
        SimpleNamespace(account="DU123", tag="TotalCashValue", value="", currency="USD"),
    ]
    adapter._ib.accountSummaryAsync = AsyncMock(return_value=sdk_rows)  # type: ignore[attr-defined]

    rows = {r.tag: r.value for r in await adapter.account_summary()}  # type: ignore[attr-defined]

    assert rows["NetLiquidation"] == Decimal("100000.50")
    assert rows["AccountType"] == Decimal("0")  # non-numeric → 0, no raise.
    assert rows["Currency"] == Decimal("0")
    assert rows["TotalCashValue"] == Decimal("0")  # empty string → 0.


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


def test_to_order_snaps_stop_price_to_penny_tick() -> None:
    """IBKR Error 110: an ATR-derived sub-penny stop must be snapped to the
    minimum price variation ($0.01) before submission."""
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(
        action="SELL",
        total_quantity=Decimal("4"),
        order_type="STP",
        aux_price=Decimal("120.29428571"),
    )
    sdk = _to_order(order)
    assert sdk.auxPrice == 120.29


def test_to_order_snaps_limit_price_to_penny_tick() -> None:
    """A sub-penny take-profit limit (e.g. 318.235) is rounded to $0.01."""
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(
        action="SELL",
        total_quantity=Decimal("7"),
        order_type="LMT",
        limit_price=Decimal("318.235"),
    )
    sdk = _to_order(order)
    assert sdk.lmtPrice == 318.24  # HALF_UP


@pytest.mark.asyncio
async def test_await_perm_id_returns_when_stamped() -> None:
    """The perm-id wait must NOT call the SDK's removed ``waitOnUpdateAsync``;
    when the broker has stamped a permId it returns cleanly."""
    from iguanatrader.contexts.trading.brokers.ib_async_client import IbAsyncIBClient

    class _Order:
        permId = 953410504

    class _Status:
        status = "Submitted"

    class _Trade:
        order = _Order()
        orderStatus = _Status()

    await IbAsyncIBClient._await_perm_id(_Trade())  # must not raise


@pytest.mark.asyncio
async def test_await_perm_id_raises_on_cancel_before_perm_id() -> None:
    """A parent cancelled/rejected before a permId lands surfaces as an error
    (so the execute handler persists a rejected/reconcilable order)."""
    from iguanatrader.contexts.trading.brokers.ib_async_client import IbAsyncIBClient

    class _Order:
        permId = 0

    class _Status:
        status = "Cancelled"

    class _Trade:
        order = _Order()
        orderStatus = _Status()

    with pytest.raises(RuntimeError, match="rejected before perm_id"):
        await IbAsyncIBClient._await_perm_id(_Trade(), what="bracket parent")


def test_value_object_translator_rejects_unsupported_sec_type() -> None:
    """Slice ``ib-translators-full`` supports STK/FUT/OPT/CASH/CRYPTO/CFD/IND.
    Anything else (warrant, bag, fund) still raises."""
    from iguanatrader.contexts.trading.brokers.client_protocol import Contract
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_contract

    bad = Contract(symbol="ABC", sec_type="WAR")
    with pytest.raises(NotImplementedError, match="sec_type='WAR'"):
        _to_contract(bad)


# ---------------------------------------------------------------------------
# Slice ``ib-translators-full`` — sec_type expansion
# ---------------------------------------------------------------------------


def test_future_contract_requires_expiry() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import Contract
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_contract

    bad = Contract(symbol="ES", sec_type="FUT", exchange="CME")
    with pytest.raises(ValueError, match="FUT contract requires"):
        _to_contract(bad)


def test_future_contract_with_expiry_builds_sdk_future() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import Contract
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_contract

    ok = Contract(symbol="ES", sec_type="FUT", exchange="CME", expiry="202612", multiplier="50")
    sdk = _to_contract(ok)
    assert sdk.sec_type == "FUT"
    assert sdk.symbol == "ES"
    assert sdk.lastTradeDateOrContractMonth == "202612"
    assert sdk.exchange == "CME"
    assert sdk.multiplier == "50"


def test_option_contract_requires_expiry_strike_right() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import Contract
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_contract

    bad = Contract(symbol="AAPL", sec_type="OPT", expiry="20261218")  # missing strike + right
    with pytest.raises(ValueError, match="OPT contract requires"):
        _to_contract(bad)


def test_option_contract_with_all_fields_builds_sdk_option() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import Contract
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_contract

    ok = Contract(
        symbol="AAPL",
        sec_type="OPT",
        exchange="SMART",
        expiry="20261218",
        strike=Decimal("250"),
        right="C",
    )
    sdk = _to_contract(ok)
    assert sdk.sec_type == "OPT"
    assert sdk.strike == 250.0
    assert sdk.right == "C"
    assert sdk.multiplier == "100"  # default for US equity options


def test_forex_contract_uses_pair_symbol() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import Contract
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_contract

    sdk = _to_contract(Contract(symbol="EUR.USD", sec_type="CASH", exchange="IDEALPRO"))
    assert sdk.sec_type == "CASH"
    assert sdk.pair == "EUR.USD"


def test_crypto_contract_defaults_paxos_exchange() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import Contract
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_contract

    sdk = _to_contract(Contract(symbol="BTC", sec_type="CRYPTO", exchange="", currency="USD"))
    assert sdk.sec_type == "CRYPTO"
    assert sdk.exchange == "PAXOS"
    assert sdk.currency == "USD"


def test_index_contract_builds_sdk_index() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import Contract
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_contract

    sdk = _to_contract(Contract(symbol="SPX", sec_type="IND", exchange="CBOE"))
    assert sdk.sec_type == "IND"
    assert sdk.symbol == "SPX"


# ---------------------------------------------------------------------------
# Slice ``ib-translators-full`` — order_type expansion (TRAIL / MOC / LOC)
# ---------------------------------------------------------------------------


def test_trail_order_with_absolute_amount() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(
        action="SELL",
        total_quantity=Decimal("10"),
        order_type="TRAIL",
        trail_amount=Decimal("5"),
    )
    sdk = _to_order(order)
    assert sdk.orderType == "TRAIL"
    assert sdk.auxPrice == 5.0


def test_trail_order_with_percent() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(
        action="SELL",
        total_quantity=Decimal("10"),
        order_type="TRAIL",
        trail_percent=Decimal("3.5"),
    )
    sdk = _to_order(order)
    assert sdk.orderType == "TRAIL"
    assert sdk.trailingPercent == 3.5


def test_trail_order_rejects_missing_trail_params() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    bad = IBOrder(action="SELL", total_quantity=Decimal("10"), order_type="TRAIL")
    with pytest.raises(ValueError, match="exactly one of"):
        _to_order(bad)


def test_trail_order_rejects_both_amount_and_percent() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    bad = IBOrder(
        action="SELL",
        total_quantity=Decimal("10"),
        order_type="TRAIL",
        trail_amount=Decimal("5"),
        trail_percent=Decimal("3"),
    )
    with pytest.raises(ValueError, match="cannot set both"):
        _to_order(bad)


def test_trail_limit_order_requires_limit_offset() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    bad = IBOrder(
        action="SELL",
        total_quantity=Decimal("10"),
        order_type="TRAIL LIMIT",
        trail_amount=Decimal("5"),
    )
    with pytest.raises(ValueError, match="TRAIL LIMIT requires limit_price"):
        _to_order(bad)


def test_trail_limit_order_full() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(
        action="SELL",
        total_quantity=Decimal("10"),
        order_type="TRAIL LIMIT",
        trail_amount=Decimal("5"),
        limit_price=Decimal("0.10"),  # offset
    )
    sdk = _to_order(order)
    assert sdk.orderType == "TRAIL LIMIT"
    assert sdk.auxPrice == 5.0
    assert sdk.lmtPriceOffset == 0.10


def test_moc_order_builds_no_extra_fields() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(action="BUY", total_quantity=Decimal("10"), order_type="MOC")
    sdk = _to_order(order)
    assert sdk.orderType == "MOC"


def test_loc_order_requires_limit_price() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    bad = IBOrder(action="BUY", total_quantity=Decimal("10"), order_type="LOC")
    with pytest.raises(ValueError, match=r"LOC.*requires limit_price"):
        _to_order(bad)


def test_loc_order_with_limit() -> None:
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(
        action="BUY",
        total_quantity=Decimal("10"),
        order_type="LOC",
        limit_price=Decimal("100.5"),
    )
    sdk = _to_order(order)
    assert sdk.orderType == "LOC"
    assert sdk.lmtPrice == 100.5


# ---------------------------------------------------------------------------
# Slice ``ibkr-execution-algos-entry`` — algo translation
# ---------------------------------------------------------------------------


def test_market_algo_kind_does_not_attach_algo_strategy() -> None:
    """``algo_kind="market"`` is a no-op: no algoStrategy / algoParams on the order."""
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(
        action="BUY",
        total_quantity=Decimal("10"),
        order_type="MKT",
        algo_kind="market",
    )
    sdk_order = _to_order(order)

    assert not hasattr(sdk_order, "algoStrategy") or sdk_order.algoStrategy is None
    assert not hasattr(sdk_order, "algoParams") or sdk_order.algoParams is None


def test_none_algo_kind_does_not_attach_algo_strategy() -> None:
    """Default ``algo_kind=None`` preserves pre-slice behaviour (no algo)."""
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(action="BUY", total_quantity=Decimal("10"), order_type="MKT")
    sdk_order = _to_order(order)

    assert not hasattr(sdk_order, "algoStrategy") or sdk_order.algoStrategy is None
    assert not hasattr(sdk_order, "algoParams") or sdk_order.algoParams is None


def test_adaptive_algo_attaches_adaptive_strategy_with_normal_priority() -> None:
    """``algo_kind="adaptive"`` sets algoStrategy='Adaptive' + adaptivePriority='Normal'."""
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(
        action="BUY",
        total_quantity=Decimal("10"),
        order_type="MKT",
        algo_kind="adaptive",
    )
    sdk_order = _to_order(order)

    assert sdk_order.algoStrategy == "Adaptive"
    assert len(sdk_order.algoParams) == 1
    assert sdk_order.algoParams[0].tag == "adaptivePriority"
    assert sdk_order.algoParams[0].value == "Normal"


def test_twap_algo_attaches_twap_strategy_with_marketable_strategy_type() -> None:
    """``algo_kind="twap"`` sets algoStrategy='Twap' + strategyType='Marketable'."""
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(
        action="BUY",
        total_quantity=Decimal("10"),
        order_type="MKT",
        algo_kind="twap",
    )
    sdk_order = _to_order(order)

    assert sdk_order.algoStrategy == "Twap"
    assert len(sdk_order.algoParams) == 1
    assert sdk_order.algoParams[0].tag == "strategyType"
    assert sdk_order.algoParams[0].value == "Marketable"


def test_algo_params_override_defaults() -> None:
    """Caller-supplied ``algo_params`` merge on top of defaults."""
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    order = IBOrder(
        action="BUY",
        total_quantity=Decimal("10"),
        order_type="MKT",
        algo_kind="adaptive",
        algo_params={"adaptivePriority": "Urgent"},
    )
    sdk_order = _to_order(order)

    assert sdk_order.algoStrategy == "Adaptive"
    assert sdk_order.algoParams[0].value == "Urgent"


def test_unsupported_algo_kind_raises_not_implemented() -> None:
    """Unknown ``algo_kind`` surfaces a NotImplementedError with the bad value."""
    from iguanatrader.contexts.trading.brokers.client_protocol import IBOrder
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_order

    # ``vwap``/``arrival_price`` ARE wired now (see ``_attach_algo``); use a
    # genuinely-unsupported strategy so the test still pins the failure path.
    order = IBOrder(
        action="BUY",
        total_quantity=Decimal("10"),
        order_type="MKT",
        algo_kind="iceberg",  # not wired
    )
    with pytest.raises(NotImplementedError, match="algo_kind='iceberg'"):
        _to_order(order)
