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

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
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


def _to_contract(c: Contract) -> Any:
    """Translate our :class:`Contract` value into an ``ib_async.Stock`` (or future sec_type)."""
    from ib_async import Stock  # lazy import — keeps module importable without dep.

    if c.sec_type == "STK":
        return Stock(c.symbol, c.exchange, c.currency)
    raise NotImplementedError(
        f"sec_type={c.sec_type!r} not yet wired in IbAsyncIBClient — "
        "extend translator when adding futures / options."
    )


def _to_order(o: IBOrder) -> Any:
    """Translate our :class:`IBOrder` into an ``ib_async.Order``."""
    from ib_async import LimitOrder, MarketOrder, StopLimitOrder, StopOrder

    qty = float(o.total_quantity)  # ib_async expects float-ish quantities.
    order: Any
    if o.order_type == "MKT":
        order = MarketOrder(o.action, qty)
    elif o.order_type == "LMT":
        if o.limit_price is None:
            raise ValueError("LMT order requires limit_price")
        order = LimitOrder(o.action, qty, float(o.limit_price))
    elif o.order_type == "STP":
        if o.aux_price is None:
            raise ValueError("STP order requires aux_price")
        order = StopOrder(o.action, qty, float(o.aux_price))
    elif o.order_type == "STP LMT":
        if o.aux_price is None or o.limit_price is None:
            raise ValueError("STP LMT order requires limit_price and aux_price")
        order = StopLimitOrder(o.action, qty, float(o.limit_price), float(o.aux_price))
    else:
        raise NotImplementedError(f"order_type={o.order_type!r} not wired")

    order.transmit = o.transmit
    if o.account is not None:
        order.account = o.account
    if o.order_ref is not None:
        order.orderRef = o.order_ref
    return order


def _from_position(p: Any) -> PositionRecord:
    return PositionRecord(
        account=p.account,
        symbol=p.contract.symbol,
        quantity=Decimal(str(p.position)),
        average_cost=Decimal(str(p.avgCost)),
        unrealized_pnl=Decimal(str(getattr(p, "unrealizedPNL", 0) or 0)),
        currency=getattr(p.contract, "currency", "USD"),
    )


def _from_account_summary_row(row: Any) -> AccountSummaryRow:
    return AccountSummaryRow(
        account=row.account,
        tag=row.tag,
        value=Decimal(str(row.value)),
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
        # event loop. Wait for the broker to stamp it.
        while not trade.order.permId:
            await ib.waitOnUpdateAsync(timeout=1.0)
            if not trade.order.permId and trade.orderStatus.status in {
                "Cancelled",
                "ApiCancelled",
                "Inactive",
            }:
                raise RuntimeError(
                    f"placeOrder rejected before perm_id assignment: status="
                    f"{trade.orderStatus.status}"
                )
        return str(trade.order.permId)

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


def build_ib_async_client_from_env() -> IbAsyncIBClient:
    """Composition-root helper — constructs an unconnected :class:`IbAsyncIBClient`.

    Connection (host/port/client_id from :class:`SecretEnv`) is performed
    by the consumer (:class:`IBKRAdapter`) inside its `start()` lifecycle.
    """
    return IbAsyncIBClient()


__all__ = ["IbAsyncIBClient", "build_ib_async_client_from_env"]
