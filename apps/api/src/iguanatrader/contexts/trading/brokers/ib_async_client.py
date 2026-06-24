# mypy: disable-error-code="no-any-unimported,no-untyped-call,attr-defined"
"""Production ``IBClient`` adapter wrapping the ``ib_async`` SDK.

Resolves the deferred-install carry-forward from slice T2:
:class:`iguanatrader.contexts.trading.brokers.client_protocol.IBClient`
ships against ``ib_async.IB`` (structurally Protocol-compatible per
the slice T2 design D7 note). This module is the explicit shim —
it translates the SDK's concrete value objects into the frozen
dataclasses our adapter consumes, and it lazily imports ``ib_async``
so the surrounding code remains importable when the dep is absent.

The higher-level :class:`IBKRAdapter` (which lives in `ibkr_adapter.py`
and already extends :class:`HeartbeatMixin` + carries the idempotency
guard via the local ``orders`` table) is the consumer of this Protocol.
The shim does NOT duplicate those concerns — it is the SDK boundary,
nothing more.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from iguanatrader.contexts.trading.brokers.client_protocol import (
    AccountSummaryRow,
    Contract,
    Execution,
    IBOrder,
    OpenOrder,
    PositionRecord,
)

if TYPE_CHECKING:
    from ib_async import IB as _IBAsyncIB

#: US-equity minimum price variation. IBKR rejects orders whose limit/stop
#: prices are not a multiple of the contract tick (Error 110); ATR-derived
#: donchian stop/target levels carry many decimals, so we snap order prices
#: to the penny before submission. (Sub-$1 / non-US-equity ticks are out of
#: scope for the MVP universe — all watchlist names trade above $1.)
_PRICE_TICK: Decimal = Decimal("0.01")

#: ``ib_async`` stamps ``permId`` on a placed order asynchronously via the
#: event loop. We yield with ``asyncio.sleep`` (NOT the SDK's removed
#: ``waitOnUpdateAsync``) and re-poll until the broker assigns it or the order
#: is rejected/cancelled, bounded by a hard timeout.
_PERMID_POLL_SECONDS: float = 0.1
_PERMID_WAIT_TIMEOUT_SECONDS: float = 10.0


def _round_to_tick(price: Decimal) -> float:
    """Snap an order price to the US-equity minimum price variation ($0.01).

    Returns a float (the SDK expects float prices). Prevents IBKR Error 110
    ("price does not conform to the minimum price variation") for the
    ATR-derived stop/target levels threaded into bracket child orders.
    """
    return float(Decimal(price).quantize(_PRICE_TICK, rounding=ROUND_HALF_UP))


def _to_contract(c: Contract) -> Any:
    """Translate our :class:`Contract` value into an ``ib_async`` SDK contract.

    Slice ``ib-translators-full`` expands beyond equities. Required
    fields per sec_type:

    * ``STK`` — symbol/exchange/currency (defaults).
    * ``FUT`` — adds ``expiry`` (YYYYMM / YYYYMMDD). Exchange almost
      always specific (e.g. ``"CME"``); SMART is rejected by IBKR.
    * ``OPT`` — adds ``expiry`` (YYYYMMDD), ``strike``, ``right``
      (``"C"`` or ``"P"``).
    * ``CASH`` — symbol is the pair (e.g. ``"EUR.USD"``); exchange
      ``"IDEALPRO"`` for spot FX. The SDK splits the pair on the dot.
    * ``CRYPTO`` — exchange ``"PAXOS"`` for IBKR-supported BTC / ETH /
      LTC. Currency is fiat (e.g. ``"USD"``).
    * ``CFD`` — UK/EU residents only; same shape as STK plus the SDK's
      :class:`ib_async.CFD` class.
    * ``IND`` — cash index (e.g. ``"SPX"``); same shape as STK but
      :class:`ib_async.Index`.
    """
    sec_type = c.sec_type.upper()

    if sec_type == "STK":
        from ib_async import Stock

        return Stock(c.symbol, c.exchange, c.currency)

    if sec_type == "FUT":
        from ib_async import Future

        if not c.expiry:
            raise ValueError("FUT contract requires non-empty 'expiry' (YYYYMM or YYYYMMDD)")
        return Future(
            symbol=c.symbol,
            lastTradeDateOrContractMonth=c.expiry,
            exchange=c.exchange,
            currency=c.currency,
            multiplier=c.multiplier or "",
            tradingClass=c.trading_class or "",
        )

    if sec_type == "OPT":
        from ib_async import Option

        if not c.expiry or c.strike is None or c.right not in {"C", "P"}:
            raise ValueError(
                "OPT contract requires expiry (YYYYMMDD), strike, and right ∈ {'C','P'}"
            )
        return Option(
            symbol=c.symbol,
            lastTradeDateOrContractMonth=c.expiry,
            strike=float(c.strike),
            right=c.right,
            exchange=c.exchange,
            currency=c.currency,
            multiplier=c.multiplier or "100",
            tradingClass=c.trading_class or "",
        )

    if sec_type == "CASH":
        from ib_async import Forex

        # IBKR's Forex expects the pair as one string ("EURUSD" or "EUR.USD").
        return Forex(c.symbol)

    if sec_type == "CRYPTO":
        from ib_async import Crypto

        return Crypto(c.symbol, c.exchange or "PAXOS", c.currency or "USD")

    if sec_type == "CFD":
        from ib_async import CFD

        return CFD(c.symbol, c.exchange, c.currency)

    if sec_type == "IND":
        from ib_async import Index

        return Index(c.symbol, c.exchange, c.currency)

    raise NotImplementedError(
        f"sec_type={c.sec_type!r} not wired in IbAsyncIBClient — "
        "supported: STK / FUT / OPT / CASH / CRYPTO / CFD / IND."
    )


def _to_order(o: IBOrder) -> Any:
    """Translate our :class:`IBOrder` into an ``ib_async.Order``.

    When ``o.algo_kind`` is set (slice ``ibkr-execution-algos-entry``),
    the ``ib_async.Order``'s ``algoStrategy`` + ``algoParams`` fields are
    populated per IBKR's API spec. The base order type (MKT/LMT/STP) is
    independent of the algo — IBKR layers the algo on top of any order
    type, though in practice we ship algos with MKT only in this slice.
    """
    from ib_async import LimitOrder, MarketOrder, Order, StopLimitOrder, StopOrder

    qty = float(o.total_quantity)  # ib_async expects float-ish quantities.
    order: Any
    if o.order_type == "MKT":
        order = MarketOrder(o.action, qty)
    elif o.order_type == "LMT":
        if o.limit_price is None:
            raise ValueError("LMT order requires limit_price")
        order = LimitOrder(o.action, qty, _round_to_tick(o.limit_price))
    elif o.order_type == "STP":
        if o.aux_price is None:
            raise ValueError("STP order requires aux_price")
        order = StopOrder(o.action, qty, _round_to_tick(o.aux_price))
    elif o.order_type == "STP LMT":
        if o.aux_price is None or o.limit_price is None:
            raise ValueError("STP LMT order requires limit_price and aux_price")
        order = StopLimitOrder(
            o.action, qty, _round_to_tick(o.limit_price), _round_to_tick(o.aux_price)
        )
    elif o.order_type in ("TRAIL", "TRAIL LIMIT", "MOC", "LOC"):
        # The SDK ``Order`` base class accepts arbitrary ``orderType``;
        # the higher-level helpers (``MarketOrder`` etc.) only cover the
        # four most common shapes. For trailing + auction types we build
        # the base ``Order`` and stamp the IBKR-specific fields directly.
        order = Order(
            action=o.action,
            totalQuantity=qty,
            orderType=o.order_type,
        )
        if o.order_type in ("TRAIL", "TRAIL LIMIT"):
            if o.trail_amount is None and o.trail_percent is None:
                raise ValueError(
                    f"{o.order_type} order requires exactly one of " "trail_amount or trail_percent"
                )
            if o.trail_amount is not None and o.trail_percent is not None:
                raise ValueError(
                    f"{o.order_type} order: cannot set both trail_amount AND trail_percent"
                )
            if o.trail_amount is not None:
                order.auxPrice = float(o.trail_amount)
            else:
                order.trailingPercent = float(o.trail_percent or 0)
            if o.order_type == "TRAIL LIMIT":
                if o.limit_price is None:
                    raise ValueError("TRAIL LIMIT requires limit_price (offset from trigger)")
                order.lmtPriceOffset = float(o.limit_price)
        elif o.order_type == "LOC":
            if o.limit_price is None:
                raise ValueError("LOC (limit-on-close) requires limit_price")
            order.lmtPrice = float(o.limit_price)
        # MOC needs no extra fields — IBKR auctions at the closing print.
    else:
        raise NotImplementedError(
            f"order_type={o.order_type!r} not wired — supported: "
            "MKT / LMT / STP / STP LMT / TRAIL / TRAIL LIMIT / MOC / LOC."
        )

    # Stamp an explicit DAY time-in-force. ib_async leaves ``tif`` empty,
    # which the IBKR Gateway's order preset rewrites to DAY (Error 10349
    # "Order TIF was set to DAY based on order preset"); rewriting the TIF of
    # a HELD bracket parent (transmit=False) cancels it before a perm-id ever
    # lands. Sending DAY up-front means the preset has nothing to rewrite, so
    # the bracket transmits cleanly. (Note: this caps bracket stop/target legs
    # at intraday persistence; multi-day protection leans on the daemon's
    # re-evaluation / cron stop-sweep.)
    order.tif = "DAY"
    order.transmit = o.transmit
    if o.account is not None:
        order.account = o.account
    if o.order_ref is not None:
        order.orderRef = o.order_ref

    if o.algo_kind is not None and o.algo_kind != "market":
        _attach_algo(order, o.algo_kind, o.algo_params)

    return order


def _attach_algo(order: Any, algo_kind: str, algo_params: dict[str, str] | None) -> None:
    """Populate ``algoStrategy`` + ``algoParams`` on an ``ib_async.Order``.

    Per IBKR's algoStrategy spec
    (https://interactivebrokers.github.io/tws-api/ibalgos.html):

    * **Adaptive**: ``algoStrategy="Adaptive"``, single param
      ``adaptivePriority``. Allowed values: ``Patient`` / ``Normal`` /
      ``Urgent``. Defaults to ``Normal`` — a sensible retail-equity
      tradeoff between fill speed and price improvement.
    * **TWAP**: ``algoStrategy="Twap"``, params ``strategyType`` (one of
      ``Marketable`` / ``Matching Midpoint`` / ``Matching Same Side`` /
      ``Matching Last``) and ``startTime`` / ``endTime`` (UTC strings).
      Defaults: ``strategyType="Marketable"`` (most aggressive — fills
      against the existing book), times left blank so IBKR uses "now"
      + a sensible end window for the order quantity.

    Callers can override defaults via ``algo_params`` (merged on top).
    """
    from ib_async import TagValue

    defaults: dict[str, dict[str, str]] = {
        "adaptive": {"adaptivePriority": "Normal"},
        "twap": {"strategyType": "Marketable"},
        "vwap": {"maxPctVol": "10"},
        "arrival_price": {"maxPctVol": "10", "riskAversion": "Neutral"},
    }
    strategy_name = {
        "adaptive": "Adaptive",
        "twap": "Twap",
        "vwap": "Vwap",
        "arrival_price": "ArrivalPx",
    }.get(algo_kind)
    if strategy_name is None:
        raise NotImplementedError(
            f"algo_kind={algo_kind!r} not wired — supported: "
            "adaptive / twap / vwap / arrival_price."
        )

    merged_params = dict(defaults[algo_kind])
    if algo_params is not None:
        merged_params.update(algo_params)

    order.algoStrategy = strategy_name
    order.algoParams = [TagValue(k, v) for k, v in merged_params.items()]


def _from_position(p: Any) -> PositionRecord:
    return PositionRecord(
        account=p.account,
        symbol=p.contract.symbol,
        quantity=Decimal(str(p.position)),
        average_cost=Decimal(str(p.avgCost)),
        unrealized_pnl=Decimal(str(getattr(p, "unrealizedPNL", 0) or 0)),
        currency=getattr(p.contract, "currency", "USD"),
    )


def _account_summary_value(raw: Any) -> Decimal:
    """Coerce an account-summary row value to Decimal, tolerating the
    non-numeric tags IBKR returns.

    ``accountSummaryAsync`` mixes numeric tags the adapter reads
    (``NetLiquidation``, ``TotalCashValue``, ``RealizedPnL``, ...) with
    string tags it does not (``AccountType="INDIVIDUAL"``,
    ``Currency="USD"``, ``TradingType=...``). Eagerly running
    ``Decimal()`` over the string tags raised ``decimal.ConversionSyntax``
    and failed the whole equity reconcile; the non-numeric tags are never
    used numerically, so coerce them to 0 instead of raising.
    """
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _from_account_summary_row(row: Any) -> AccountSummaryRow:
    return AccountSummaryRow(
        account=row.account,
        tag=row.tag,
        value=_account_summary_value(row.value),
        currency=getattr(row, "currency", "USD") or "USD",
    )


def _from_open_order(t: Any) -> OpenOrder:
    order = t.order
    contract = t.contract
    status = getattr(t, "orderStatus", None)
    return OpenOrder(
        perm_id=int(order.permId or 0),
        client_id=int(order.clientId or 0),
        order_ref=getattr(order, "orderRef", None) or None,
        symbol=contract.symbol,
        action=order.action,
        total_quantity=Decimal(str(order.totalQuantity)),
        order_type=order.orderType,
        limit_price=Decimal(str(order.lmtPrice)) if order.lmtPrice else None,
        status=getattr(status, "status", "Submitted") if status else "Submitted",
    )


def _from_execution(fill: Any) -> Execution:
    exec_obj = fill.execution
    contract = fill.contract
    commission_report = getattr(fill, "commissionReport", None)
    commission = Decimal("0")
    commission_currency = "USD"
    if commission_report is not None:
        commission = Decimal(str(commission_report.commission or 0))
        commission_currency = commission_report.currency or "USD"
    raw_time = exec_obj.time
    if isinstance(raw_time, str):
        # ib_async sometimes returns "YYYYMMDD  HH:MM:SS  TZ" — be defensive.
        try:
            time_dt = datetime.fromisoformat(raw_time)
        except ValueError:
            time_dt = datetime.now(UTC)
    else:
        time_dt = raw_time
    return Execution(
        exec_id=exec_obj.execId,
        perm_id=int(exec_obj.permId or 0),
        order_ref=getattr(exec_obj, "orderRef", None) or None,
        account=exec_obj.acctNumber,
        symbol=contract.symbol,
        side=exec_obj.side,
        shares=Decimal(str(exec_obj.shares)),
        price=Decimal(str(exec_obj.price)),
        time=time_dt,
        commission=commission,
        commission_currency=commission_currency,
    )


class IbAsyncIBClient:
    """Production :class:`IBClient` — thin shim over ``ib_async.IB``.

    Construction takes the ``ib_async.IB`` instance explicitly so the
    consumer (typically :class:`IBKRAdapter`) controls connection
    lifecycle. The shim does NOT touch ``HeartbeatMixin`` or the
    idempotency table — those live in the higher-level adapter.
    """

    def __init__(self, ib: _IBAsyncIB | None = None) -> None:
        self._ib: _IBAsyncIB | None = ib

    def _ensure(self) -> _IBAsyncIB:
        if self._ib is None:
            from ib_async import IB

            self._ib = IB()
        return self._ib

    async def connect_async(self, host: str, port: int, client_id: int) -> None:
        ib = self._ensure()
        await ib.connectAsync(host=host, port=port, clientId=client_id)

    def disconnect(self) -> None:
        if self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()

    async def req_current_time(self) -> datetime:
        ib = self._ensure()
        result = await ib.reqCurrentTimeAsync()
        if isinstance(result, datetime):
            return result if result.tzinfo else result.replace(tzinfo=UTC)
        # ib_async sometimes returns int epoch — be defensive.
        return datetime.fromtimestamp(int(result), tz=UTC)

    async def place_order(self, contract: Contract, order: IBOrder) -> str:
        ib = self._ensure()
        trade = ib.placeOrder(_to_contract(contract), _to_order(order))
        # placeOrder returns a Trade synchronously; perm_id arrives async via the
        # event loop. Yield to let ib_async process broker updates, then re-poll.
        await self._await_perm_id(trade)
        return str(trade.order.permId)

    async def place_bracket_order(
        self,
        contract: Contract,
        parent: IBOrder,
        stop_loss: IBOrder,
        take_profit: IBOrder | None,
    ) -> str:
        # ib_async's ``bracketOrder`` helper assumes a LIMIT parent, so build
        # the bracket by hand to support a market entry. The last leg carries
        # ``transmit=True`` so IBKR receives the whole bracket atomically once
        # the parent + children are queued; children share an OCA group so a
        # fill on one cancels the other.
        ib = self._ensure()
        ib_contract = _to_contract(contract)
        parent_ord = _to_order(parent)
        parent_ord.transmit = False
        parent_ord.orderId = ib.client.getReqId()
        oca_group = f"oca-{parent_ord.orderId}"
        stop_ord = _to_order(stop_loss)
        stop_ord.parentId = parent_ord.orderId
        children = []
        if take_profit is not None:
            tp_ord = _to_order(take_profit)
            tp_ord.parentId = parent_ord.orderId
            tp_ord.ocaGroup = oca_group
            tp_ord.ocaType = 1
            tp_ord.transmit = False
            stop_ord.ocaGroup = oca_group
            stop_ord.ocaType = 1
            children = [tp_ord, stop_ord]
        else:
            children = [stop_ord]
        stop_ord.transmit = True  # last leg transmits the whole bracket atomically
        trade = ib.placeOrder(ib_contract, parent_ord)
        for child in children:
            ib.placeOrder(ib_contract, child)
        await self._await_perm_id(trade, what="bracket parent")
        return str(trade.order.permId)

    @staticmethod
    async def _await_perm_id(trade: Any, *, what: str = "order") -> None:
        """Poll until ib_async stamps ``permId`` on a placed order.

        Replaces the SDK's removed ``waitOnUpdateAsync``: ``asyncio.sleep``
        yields to the event loop so ib_async can process broker updates, and we
        re-check the trade. Raises if the order is rejected/cancelled before a
        ``permId`` lands, or if the bounded wait elapses.
        """
        waited = 0.0
        while not trade.order.permId:
            await asyncio.sleep(_PERMID_POLL_SECONDS)
            waited += _PERMID_POLL_SECONDS
            if not trade.order.permId and trade.orderStatus.status in {
                "Cancelled",
                "ApiCancelled",
                "Inactive",
            }:
                raise RuntimeError(
                    f"{what} rejected before perm_id assignment: "
                    f"status={trade.orderStatus.status}"
                )
            if waited >= _PERMID_WAIT_TIMEOUT_SECONDS:
                raise TimeoutError(
                    f"{what} perm_id not stamped within {_PERMID_WAIT_TIMEOUT_SECONDS}s; "
                    f"status={trade.orderStatus.status}"
                )

    async def cancel_order(self, broker_order_id: str) -> None:
        ib = self._ensure()
        for trade in ib.openTrades():
            if str(trade.order.permId) == broker_order_id:
                ib.cancelOrder(trade.order)
                return
        # Order not found locally — issue cancel by perm_id where supported.

    async def positions(self) -> Iterable[PositionRecord]:
        ib = self._ensure()
        rows = await ib.reqPositionsAsync()
        return [_from_position(p) for p in rows]

    async def account_summary(self) -> Iterable[AccountSummaryRow]:
        ib = self._ensure()
        rows = await ib.accountSummaryAsync()
        return [_from_account_summary_row(r) for r in rows]

    async def req_executions(self, since: datetime) -> Iterable[Execution]:
        ib = self._ensure()
        from ib_async import ExecutionFilter

        filt = ExecutionFilter()
        filt.time = since.strftime("%Y%m%d-%H:%M:%S")
        fills = await ib.reqExecutionsAsync(filt)
        return [_from_execution(f) for f in fills]

    async def req_all_open_orders(self) -> Iterable[OpenOrder]:
        ib = self._ensure()
        await ib.reqAllOpenOrdersAsync()
        return [_from_open_order(t) for t in ib.openTrades()]

    async def req_historical_bars(
        self,
        *,
        symbol: str,
        duration_str: str,
        bar_size: str,
        what_to_show: str = "TRADES",
        use_rth: bool = True,
    ) -> Iterable[Any]:
        """Fetch historical bars for ``symbol`` (slice T4-followup-market-data §2.4).

        Wraps ``ib_async.IB.reqHistoricalDataAsync`` after qualifying
        the symbol as a US-equity Stock contract on SMART/USD.
        ``duration_str`` is IBKR's duration spec (e.g. ``"200 D"``,
        ``"30 D"``, ``"1 Y"``); ``bar_size`` is e.g. ``"1 day"``,
        ``"1 hour"``, ``"1 min"``. The ingestor is the only caller.
        """
        from ib_async import Stock

        ib = self._ensure()
        contract = Stock(symbol, "SMART", "USD")
        await ib.qualifyContractsAsync(contract)
        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr=duration_str,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=use_rth,
            formatDate=2,  # epoch seconds; tz-naive UTC
        )
        return list(bars or [])


def build_ib_async_client_from_env() -> IbAsyncIBClient:
    """Composition-root helper — constructs an unconnected :class:`IbAsyncIBClient`.

    Connection (host/port/client_id from :class:`SecretEnv`) is performed
    by the consumer (:class:`IBKRAdapter`) inside its `start()` lifecycle.
    """
    return IbAsyncIBClient()


__all__ = ["IbAsyncIBClient", "build_ib_async_client_from_env"]
