"""Protocol for the IB client surface (slice T2 design D7).

Production wiring of ``ib_async`` is **deferred** to a deployment
slice — adding a real broker SDK is a security-review item (API
contract drift, secret-handling for ``IBKR_USERNAME`` / ``IBKR_PASSWORD``
at TWS gateway, version pinning, paper-vs-live port enforcement).

This module declares the minimal surface :class:`IBKRAdapter` consumes:

* :class:`IBClient` Protocol — the methods the adapter calls.
* :class:`Contract`, :class:`IBOrder`, :class:`OpenOrder`,
  :class:`Execution`, :class:`PositionRecord` — value-object shapes
  matching ``ib_async``'s public API. We use frozen dataclasses (NOT
  :class:`Protocol`) for these so the in-tree fake at
  ``tests/_fakes/ib_async_fake.py`` can construct them without
  importing the real package.

When the production wiring lands, ``ib_async.IB`` satisfies
:class:`IBClient` structurally (``ib_async`` already exposes these
methods with these signatures), and the adapter's ``client_factory``
default flips from ``None`` (test-injection required) to
``lambda: ib_async.IB()``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Contract:
    """Minimal :class:`ib_async.Stock` shape — symbol + exchange + currency."""

    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    sec_type: str = "STK"


@dataclass(frozen=True, slots=True)
class IBOrder:
    """Outbound order shape passed to :meth:`IBClient.place_order`.

    Mirrors the subset of ``ib_async.Order`` fields the adapter sets.
    Frozen so the adapter cannot mutate post-construction; the
    in-tree fake builds new instances when modelling state changes.
    """

    action: str  # "BUY" / "SELL"
    total_quantity: Decimal
    order_type: str  # "MKT" / "LMT" / "STP" / "STP LMT"
    limit_price: Decimal | None = None
    aux_price: Decimal | None = None  # stop price for STP / STP LMT
    transmit: bool = True
    account: str | None = None
    order_ref: str | None = None  # Mirror of NewOrder.client_order_id for
    # IBKR-side tracing.


@dataclass(frozen=True, slots=True)
class OpenOrder:
    """Result element of :meth:`IBClient.req_all_open_orders`."""

    perm_id: int  # Stable across API sessions.
    client_id: int
    order_ref: str | None
    symbol: str
    action: str
    total_quantity: Decimal
    order_type: str
    limit_price: Decimal | None
    status: str  # "Submitted" / "Filled" / "PendingCancel" / etc.


@dataclass(frozen=True, slots=True)
class Execution:
    """Result element of :meth:`IBClient.req_executions`."""

    exec_id: str  # Broker-stable; idempotency key for FillEvent.
    perm_id: int
    order_ref: str | None
    account: str
    symbol: str
    side: str  # "BOT" / "SLD" — IBKR's convention.
    shares: Decimal
    price: Decimal
    time: datetime
    commission: Decimal = Decimal("0")
    commission_currency: str = "USD"


@dataclass(frozen=True, slots=True)
class PositionRecord:
    """Result element of :meth:`IBClient.positions`."""

    account: str
    symbol: str
    quantity: Decimal
    average_cost: Decimal
    unrealized_pnl: Decimal = Decimal("0")
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class AccountSummaryRow:
    """Result element of :meth:`IBClient.account_summary`."""

    account: str
    tag: str  # ``NetLiquidation`` / ``TotalCashValue`` / etc.
    value: Decimal
    currency: str = "USD"


# ----------------------------------------------------------------------
# Protocol
# ----------------------------------------------------------------------


class IBClient(Protocol):
    """Minimal IB client surface consumed by :class:`IBKRAdapter`.

    Async-flavoured to match ``ib_async``'s contemporary public API.
    The in-tree fake at ``apps/api/tests/_fakes/ib_async_fake.py``
    satisfies this Protocol; tests inject the fake via
    :func:`IBKRAdapter`'s ``client_factory`` parameter.
    """

    async def connect_async(self, host: str, port: int, client_id: int) -> None:
        """Open the TCP connection to TWS / IB Gateway."""
        ...

    def disconnect(self) -> None:
        """Close the TCP connection. Idempotent."""
        ...

    async def req_current_time(self) -> datetime:
        """Return broker's current UTC time. Used as heartbeat ping."""
        ...

    async def place_order(self, contract: Contract, order: IBOrder) -> str:
        """Submit ``order`` against ``contract``. Return broker order ID
        (``perm_id`` as string)."""
        ...

    async def cancel_order(self, broker_order_id: str) -> None:
        """Cancel a previously-submitted order by broker order ID."""
        ...

    async def positions(self) -> Iterable[PositionRecord]:
        """Return every open position across accounts."""
        ...

    async def account_summary(self) -> Iterable[AccountSummaryRow]:
        """Return summary rows for the current account."""
        ...

    async def req_executions(self, since: datetime) -> Iterable[Execution]:
        """Return executions filled at or after ``since`` UTC."""
        ...

    async def req_all_open_orders(self) -> Iterable[OpenOrder]:
        """Return all open orders the broker knows about for the account."""
        ...


__all__ = [
    "AccountSummaryRow",
    "Contract",
    "Execution",
    "IBClient",
    "IBOrder",
    "OpenOrder",
    "PositionRecord",
]
