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
    """IBKR contract value-object — covers equity + futures + options + FX + crypto.

    The required fields per ``sec_type``:

    * ``STK`` — symbol, exchange, currency. (Equities — original default.)
    * ``FUT`` — symbol, ``expiry`` (YYYYMM or YYYYMMDD), exchange, currency.
    * ``OPT`` — symbol, ``expiry`` (YYYYMMDD), ``strike``, ``right``
      (``"C"`` call or ``"P"`` put), exchange, currency.
    * ``CASH`` — symbol = pair (e.g. ``"EUR.USD"``), exchange
      (typically ``"IDEALPRO"``).
    * ``CRYPTO`` — symbol, exchange (typically ``"PAXOS"``), currency.
    * ``CFD`` — symbol, exchange, currency (UK/EU equities only — IBKR
      blocks US residents per regulator rules).
    * ``IND`` — symbol, exchange, currency (cash indices like ``"SPX"``).

    All extension fields are optional with ``None`` defaults; the
    translator in :mod:`ib_async_client` validates the sec-type-specific
    requirements when building the SDK contract.
    """

    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    sec_type: str = "STK"
    # Derivative / FX / crypto extensions. Optional so equity callers
    # keep their existing 4-field constructor signature.
    expiry: str | None = None  # YYYYMM or YYYYMMDD (FUT / OPT)
    strike: Decimal | None = None  # OPT only
    right: str | None = None  # "C" or "P" (OPT only)
    multiplier: str | None = None  # FUT / OPT contract multiplier (e.g. "100")
    trading_class: str | None = None  # Optional disambiguator for FUT/OPT


@dataclass(frozen=True, slots=True)
class IBOrder:
    """Outbound order shape passed to :meth:`IBClient.place_order`.

    Mirrors the subset of ``ib_async.Order`` fields the adapter sets.
    Frozen so the adapter cannot mutate post-construction; the
    in-tree fake builds new instances when modelling state changes.
    """

    action: str  # "BUY" / "SELL"
    total_quantity: Decimal
    # Allowed order types — covered by :func:`_to_order` in
    # ``ib_async_client``:
    #
    # * ``MKT``       — market order; fills at best available price.
    # * ``LMT``       — limit; fills only at ``limit_price`` or better.
    # * ``STP``       — stop; once trigger price ``aux_price`` is hit,
    #                   becomes a market order.
    # * ``STP LMT``   — stop-limit; once ``aux_price`` is hit, becomes
    #                   a limit at ``limit_price``.
    # * ``TRAIL``     — trailing stop; trigger price follows the market
    #                   by ``trail_amount`` or ``trail_percent``.
    # * ``TRAIL LIMIT`` — trailing stop-limit; same trail logic plus a
    #                   limit offset (``limit_price`` offset from trigger).
    # * ``MOC``       — market-on-close; queues a market order auctioned
    #                   at the closing print.
    # * ``LOC``       — limit-on-close; queues a limit at ``limit_price``,
    #                   only fills if the closing print honours it.
    order_type: str
    limit_price: Decimal | None = None
    aux_price: Decimal | None = None  # stop price for STP / STP LMT
    # Trailing-stop parameters (TRAIL / TRAIL LIMIT). Exactly one of
    # ``trail_amount`` or ``trail_percent`` must be set; the translator
    # raises ValueError otherwise. The values are absolute (currency
    # amount per share) and percentage-of-trigger respectively.
    trail_amount: Decimal | None = None
    trail_percent: Decimal | None = None
    transmit: bool = True
    account: str | None = None
    order_ref: str | None = None  # Mirror of NewOrder.client_order_id for
    # IBKR-side tracing.
    # Slice ``ibkr-execution-algos-entry`` (expanded in
    # ``ib-translators-full``): when set, the translator in
    # ``ib_async_client._to_order`` attaches ``algoStrategy`` +
    # ``algoParams`` to the ``ib_async.Order``. Allowed values:
    #
    # * ``None`` / ``"market"`` — no algo (default; raw order).
    # * ``"adaptive"`` — IBKR's smart-routing single-order algo.
    #   Param: ``adaptivePriority`` ∈ {Patient, Normal, Urgent}.
    # * ``"twap"`` — time-weighted average price (sliced execution).
    #   Param: ``strategyType`` ∈ {Marketable, Matching Midpoint,
    #   Matching Same Side, Matching Last} + optional startTime/endTime.
    # * ``"vwap"`` — volume-weighted average price.
    #   Param: ``maxPctVol`` (max % of volume; default 10).
    # * ``"arrival_price"`` — minimises slippage vs the arrival price
    #   (price at submission). Params: ``maxPctVol``, ``riskAversion``
    #   ∈ {Get Done, Aggressive, Neutral, Passive}.
    #
    # The default ``None`` preserves pre-slice behaviour so existing
    # callers do not need to change.
    algo_kind: str | None = None
    algo_params: dict[str, str] | None = None


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

    async def place_bracket_order(
        self,
        contract: Contract,
        parent: IBOrder,
        stop_loss: IBOrder,
        take_profit: IBOrder | None,
    ) -> str:
        """Submit an entry with broker-side protective children (STP + optional
        LMT take-profit) transmitted atomically with parent/OCA linkage. Return
        the parent's broker order id (perm_id)."""
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
