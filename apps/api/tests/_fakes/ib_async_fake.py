"""In-tree fake of the :class:`IBClient` Protocol (slice T2 testing).

The fake is intentionally simple: a deterministic in-memory state
machine the test author drives via attribute assignment +
``configure_*`` helpers. No threading, no asyncio quirks — just plain
dict-backed state.

Usage::

    fake = FakeIBClient()
    fake.next_perm_id = 42
    fake.connect_should_raise = _IBAuthError("bad creds")  # 1-shot
    adapter = IBKRAdapter(brokerage=..., client_factory=lambda: fake)
    await adapter.connect()  # raises BrokerAuthError
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from iguanatrader.contexts.trading.brokers.client_protocol import (
    AccountSummaryRow,
    Contract,
    Execution,
    IBOrder,
    OpenOrder,
    PositionRecord,
)
from iguanatrader.contexts.trading.brokers.ibkr_adapter import _IBAuthError
from iguanatrader.shared.time import now as utc_now


class FakeIBClient:
    """In-memory IBClient implementation for tests.

    Knobs:

    * ``connect_failures``: number of times ``connect_async`` should raise
      a generic Exception before succeeding (drives reconnect-loop tests).
    * ``connect_should_raise_auth``: if ``True``, ``connect_async``
      raises :class:`_IBAuthError` (drives auth-short-circuit tests).
    * ``heartbeat_failures``: counter — heartbeat raises until reaches 0.
    * ``next_perm_id``: monotonically increases per ``place_order`` call.
    * ``executions``: list of :class:`Execution` returned by
      ``req_executions``. Tests append to drive reconciliation flows.
    * ``open_orders``: list of :class:`OpenOrder` returned by
      ``req_all_open_orders``.
    * ``positions_list`` + ``account_rows``: drive ``positions`` /
      ``account_summary``.
    """

    def __init__(self) -> None:
        self.connect_failures: int = 0
        self.connect_should_raise_auth: bool = False
        self.heartbeat_failures: int = 0
        self.disconnect_calls: int = 0
        self.connect_calls: int = 0
        self.placed_orders: list[tuple[Contract, IBOrder]] = []
        self.placed_brackets: list[tuple[Contract, IBOrder, IBOrder, IBOrder | None]] = []
        self.cancelled_orders: list[str] = []
        self.next_perm_id: int = 1000
        self.executions: list[Execution] = []
        self.open_orders: list[OpenOrder] = []
        self.positions_list: list[PositionRecord] = []
        self.account_rows: list[AccountSummaryRow] = []
        self._connected: bool = False

    # ------------------------------------------------------------------
    # IBClient Protocol surface
    # ------------------------------------------------------------------

    async def connect_async(self, host: str, port: int, client_id: int) -> None:
        self.connect_calls += 1
        if self.connect_should_raise_auth:
            raise _IBAuthError("FakeIBClient configured to fail auth")
        if self.connect_failures > 0:
            self.connect_failures -= 1
            raise ConnectionError(
                f"FakeIBClient.connect_async simulated failure (remaining={self.connect_failures})"
            )
        self._connected = True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    async def req_current_time(self) -> datetime:
        if self.heartbeat_failures > 0:
            self.heartbeat_failures -= 1
            raise TimeoutError(
                f"FakeIBClient.req_current_time simulated heartbeat failure "
                f"(remaining={self.heartbeat_failures})"
            )
        return utc_now()

    async def place_order(self, contract: Contract, order: IBOrder) -> str:
        if not self._connected:
            raise ConnectionError("FakeIBClient.place_order: not connected")
        self.placed_orders.append((contract, order))
        perm_id = self.next_perm_id
        self.next_perm_id += 1
        return str(perm_id)

    async def place_bracket_order(
        self,
        contract: Contract,
        parent: IBOrder,
        stop_loss: IBOrder,
        take_profit: IBOrder | None,
    ) -> str:
        if not self._connected:
            raise ConnectionError("FakeIBClient.place_bracket_order: not connected")
        self.placed_brackets.append((contract, parent, stop_loss, take_profit))
        perm_id = self.next_perm_id
        self.next_perm_id += 1
        return str(perm_id)

    async def cancel_order(self, broker_order_id: str) -> None:
        if not self._connected:
            raise ConnectionError("FakeIBClient.cancel_order: not connected")
        self.cancelled_orders.append(broker_order_id)

    async def positions(self) -> Iterable[PositionRecord]:
        return list(self.positions_list)

    async def account_summary(self) -> Iterable[AccountSummaryRow]:
        return list(self.account_rows)

    async def req_executions(self, since: datetime) -> Iterable[Execution]:
        return [e for e in self.executions if e.time >= since]

    async def req_all_open_orders(self) -> Iterable[OpenOrder]:
        return list(self.open_orders)

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def add_execution(
        self,
        *,
        order_ref: str | None = None,
        symbol: str = "AAPL",
        shares: Decimal = Decimal("1"),
        price: Decimal = Decimal("100"),
        time: datetime | None = None,
        commission: Decimal = Decimal("1"),
    ) -> Execution:
        ev = Execution(
            exec_id=str(uuid4()),
            perm_id=self.next_perm_id - 1,
            order_ref=order_ref,
            account="DU000000",
            symbol=symbol,
            side="BOT",
            shares=shares,
            price=price,
            time=time or utc_now(),
            commission=commission,
        )
        self.executions.append(ev)
        return ev

    def configure_account_equity(
        self,
        *,
        net_liquidation: Decimal = Decimal("100000"),
        cash: Decimal = Decimal("50000"),
        realized: Decimal = Decimal("0"),
        unrealized: Decimal = Decimal("0"),
    ) -> None:
        self.account_rows = [
            AccountSummaryRow(account="DU000000", tag="NetLiquidation", value=net_liquidation),
            AccountSummaryRow(account="DU000000", tag="TotalCashValue", value=cash),
            AccountSummaryRow(account="DU000000", tag="RealizedPnL", value=realized),
            AccountSummaryRow(account="DU000000", tag="UnrealizedPnL", value=unrealized),
        ]


__all__: list[str] = ["FakeIBClient"]
