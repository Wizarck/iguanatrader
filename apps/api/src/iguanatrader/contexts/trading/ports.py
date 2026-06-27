"""Trading-context Port protocols + supporting value types.

Per design D1: :class:`BrokerPort` and :class:`StrategyPort` are PEP 544
:class:`Protocol` subclasses of :class:`iguanatrader.shared.ports.Port`.
Concrete adapters in slice T2 (IBKR) and slice T3 (Donchian) satisfy the
contract structurally; ``mypy --strict`` enforces conformance.

The supporting value types (:class:`NewOrder`, :class:`FillEvent`,
:class:`Position`, :class:`BarHistory`, :class:`Proposal`) are minimal
shapes adequate for the protocols' signatures. They are dataclasses, not
ORM models — the ORM models live in :mod:`iguanatrader.contexts.trading.models`
and pass through :class:`Proposal` only as a payload of the in-process
``ProposalCreated`` event.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, NewType, Protocol, runtime_checkable
from uuid import UUID, uuid5

from iguanatrader.shared.ports import Port

# ----------------------------------------------------------------------
# Newtypes + small value objects
# ----------------------------------------------------------------------

#: Broker-side order identifier (string newtype). Caller code stores the
#: value on :attr:`Order.broker_order_id` after the broker confirms.
BrokerOrderId = NewType("BrokerOrderId", str)


@dataclass(frozen=True, slots=True)
class NewOrder:
    """Order shape passed to :meth:`BrokerPort.place_order`.

    Decoupled from the ORM ``Order`` model so adapters don't have to
    import SQLAlchemy types. The service constructs a :class:`NewOrder`
    from an approved :class:`Proposal` + the broker config.
    """

    tenant_id: UUID
    trade_id: UUID
    symbol: str
    side: str
    quantity: Decimal
    order_type: str
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    # Audit #6 (minimal): the strategy's protective take-profit target,
    # threaded from ``TradeProposal.target_price`` at execute time. A plain
    # market entry order does not transmit it to the broker yet (native
    # bracket/OCO is the #6-bracket follow-up that needs live IBKR), but the
    # entry order row records it so the protective intent is auditable and
    # the adapter can attach the bracket child once that lands. ``None``
    # when the proposal did not commit to a target.
    target_price: Decimal | None = None
    # Slice T2 (ibkr-adapter-resilient) — caller-supplied idempotency key.
    # When set (UUIDv4), the broker adapter dedupes a duplicate
    # ``place_order`` against the same ``client_order_id`` and returns the
    # cached :type:`BrokerOrderId` without re-submitting. Old call sites
    # that leave it ``None`` still work; T2's adapter raises
    # ``ValueError`` if ``None`` because idempotency is non-negotiable
    # for live broker integration. Documented in T2 retro carry-forward.
    client_order_id: UUID | None = None
    # Slice ``ibkr-execution-algos-entry``: which IBKR execution algo
    # to attach to the order. Allowed values:
    # ``None`` / ``"market"`` (default, no algo — plain market order),
    # ``"adaptive"`` (IBKR's smart-routing, priority=Normal),
    # ``"twap"`` (time-weighted average price slicing).
    # The :class:`RiskCaps.execution_algo` cap (default ``"adaptive"``)
    # is the canonical source; the service reads the cap and populates
    # this field per-order. Bare instantiation defaults to ``None`` for
    # backwards-compat with existing tests.
    algo_kind: str | None = None


@dataclass(frozen=True, slots=True)
class FillEvent:
    """Broker-emitted fill notification.

    Yielded by :meth:`BrokerPort.reconcile_fills` (post-disconnect
    reconciliation) and emitted on the wire via the live fill stream.
    The service translates this into a ``Fill`` ORM row + an
    ``OrderFilled`` MessageBus event.
    """

    tenant_id: UUID
    order_id: UUID
    quantity_filled: Decimal
    fill_price: Decimal
    commission: Decimal
    commission_currency: str
    filled_at: datetime
    broker_fill_id: str | None = None


@dataclass(frozen=True, slots=True)
class Position:
    """Snapshot of a broker-side position for a single symbol."""

    tenant_id: UUID
    symbol: str
    quantity: Decimal
    average_price: Decimal
    unrealized_pnl: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class WorkingOrder:
    """A broker-side order currently resting/working at the broker.

    Slice ``position-review-broker-visibility``: the position-review read
    model needs to see what protective orders are ACTUALLY live at IBKR —
    the resting stop-loss (``STP`` / ``STP LMT``) and take-profit (``LMT``)
    legs attached to an open position — to reconcile them against the
    DB-intended stop/target. Distinct from the broker-client
    :class:`~iguanatrader.contexts.trading.brokers.client_protocol.OpenOrder`
    value (which carries IBKR-session metadata); the adapter translates one
    into the other, mapping the IBKR ``auxPrice`` of a stop order into
    :attr:`stop_price` so the trigger level is visible (``OpenOrder`` only
    exposes ``limit_price``, which is empty for a plain stop).
    """

    tenant_id: UUID
    symbol: str
    action: str  # IBKR convention: "BUY" / "SELL".
    quantity: Decimal
    order_type: str  # "STP" / "LMT" / "STP LMT" / "MKT" / ...
    limit_price: Decimal | None
    stop_price: Decimal | None  # IBKR auxPrice — the stop trigger level.
    order_ref: str | None
    status: str


@dataclass(frozen=True, slots=True)
class EquitySnapshotValue:
    """Plain-data equity snapshot returned by
    :meth:`BrokerPort.get_account_equity`.

    Distinct from the ORM ``EquitySnapshot`` row (which is
    persistence-layer); the service converts on its way to the DB +
    bus.
    """

    tenant_id: UUID
    mode: str
    account_equity: Decimal
    cash_balance: Decimal
    realized_pnl_today: Decimal
    unrealized_pnl: Decimal
    currency: str
    snapshot_kind: str
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class Bar:
    """Single OHLCV bar — minimum shape required by strategy evaluators."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class BarHistory:
    """Sequence of historical bars passed to :meth:`StrategyPort.evaluate`.

    The strategy SHALL only inspect ``bars[t]`` where ``t < now`` —
    *no lookahead*. T3's property tests (``test_strategy_no_lookahead.py``)
    enforce the invariant via Hypothesis-generated synthetic histories.
    """

    symbol: str
    bars: Sequence[Bar]


@dataclass(frozen=True, slots=True)
class StrategyConfigSnapshot:
    """Read-only view of a :class:`StrategyConfig` row.

    Strategies receive this on every :meth:`StrategyPort.evaluate` call
    so they pick up hot-reloaded params (FR4) without holding a
    reference to a long-lived ORM instance.
    """

    id: UUID
    tenant_id: UUID
    strategy_kind: str
    symbol: str
    params: dict[str, Any]
    enabled: bool
    version: int


@dataclass(frozen=True, slots=True)
class Proposal:
    """In-memory representation of a trade proposal — return type of
    :meth:`StrategyPort.evaluate` and payload of
    :class:`iguanatrader.contexts.trading.events.ProposalCreated`.

    Distinct from the ORM ``TradeProposal`` row (which the service
    persists on its way out of ``propose``). ``research_brief_id`` is
    optional; it gets populated post-R5 by the synthesizer.
    """

    tenant_id: UUID
    strategy_config_id: UUID
    symbol: str
    side: str
    quantity: Decimal
    entry_price_indicative: Decimal
    stop_price: Decimal
    confidence_score: Decimal | None
    reasoning: dict[str, Any]
    mode: str
    correlation_id: UUID
    research_brief_id: UUID | None = None
    # Protective take-profit level the strategy commits to (long: above
    # entry; short: below entry). Threaded into ``TradeProposal.target_price``
    # at persist time so the side-aware ``stop_hit_sweep`` can emit a
    # ``CloseTradeRequested(reason="target")``. ``None`` when the strategy
    # sets no fixed target (e.g. trailing-only exits).
    target_price: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------
# Protocols
# ----------------------------------------------------------------------


@runtime_checkable
class BrokerPort(Port, Protocol):
    """Broker-side interface — implemented by slice T2's IBKR adapter.

    Concrete adapters satisfy the protocol structurally (no inheritance
    required); ``mypy --strict`` flags any missing or mistyped method.
    The ``@runtime_checkable`` decorator is required on each Protocol
    subclass (it does NOT inherit from :class:`Port`); a defensive
    ``isinstance(adapter, BrokerPort)`` check at module boundaries works
    accordingly — but the primary enforcement is static.
    """

    async def place_order(self, order: NewOrder) -> BrokerOrderId:
        """Submit ``order`` to the broker. Return the broker-side ID.

        Raises :class:`iguanatrader.shared.errors.IntegrationError` on
        broker-side failure; the service maps that to RFC 7807 502 if
        surfaced via API.
        """
        ...

    async def cancel_order(self, broker_order_id: BrokerOrderId) -> None:
        """Cancel a previously-submitted order."""
        ...

    def reconcile_fills(self, since: datetime) -> AsyncIterator[FillEvent]:
        """Yield every fill the broker recorded after ``since``.

        Used on reconnect (slice T2 ``HeartbeatMixin`` integration) to
        catch up on fills that arrived while the adapter was disconnected.
        Adapters wrapping batch-paginated APIs are expected to translate
        pagination into the async-iterator shape internally; the
        consumer (``TradingService``) does NOT manage tokens.
        """
        ...

    async def get_position(self, symbol: str) -> Position:
        """Return the current broker-side position for ``symbol``."""
        ...

    async def list_positions(self) -> Sequence[Position]:
        """Return every broker-side position currently held.

        Slice ``dual-daemon-followups`` Phase-2.5. The reconcile path
        (:meth:`DaemonLifecycleService.reconcile_with_ibkr`) needs to
        diff the daemon's open-trade view against the broker book to
        close any local trade IBKR no longer holds (typically because
        the operator flat-closed the position manually via TWS while
        the daemon was off). Returns only non-zero positions — zero-
        quantity rows are filtered out adapter-side.
        """
        ...

    async def get_account_equity(self) -> EquitySnapshotValue:
        """Return a fresh equity snapshot for the active account."""
        ...

    async def list_working_orders(self) -> Sequence[WorkingOrder]:
        """Return every order currently resting/working at the broker.

        Slice ``position-review-broker-visibility``. The position-review
        read model uses this to see the protective stop / take-profit legs
        ACTUALLY live at IBKR for each open position, and reconcile them
        against the DB-intended levels. Read-only; never mutates broker
        state. Adapters translate their native open-order shape into
        :class:`WorkingOrder`, surfacing the IBKR ``auxPrice`` as
        :attr:`WorkingOrder.stop_price`.
        """
        ...


@runtime_checkable
class StrategyPort(Port, Protocol):
    """Strategy-side interface — implemented by slice T3's
    :class:`DonchianATRStrategy` (and any future strategy).

    The contract is intentionally tiny: a name, a version, and an
    evaluator. The evaluator MUST NOT inspect bars beyond ``now`` —
    the no-lookahead invariant is enforced by T3's property tests.
    """

    def name(self) -> str:
        """Return the strategy kind (e.g. ``'donchian_atr'``).

        Matches the :attr:`StrategyConfig.strategy_kind` column so the
        manager (slice T3) can dispatch by kind for hot-reload.
        """
        ...

    def version(self) -> str:
        """Return the strategy version string (e.g. ``'1.2.0'``).

        Matches the :attr:`StrategyConfig.version` column so the
        manager can swap the running instance atomically when a config
        update bumps the version (FR4).
        """
        ...

    def evaluate(
        self,
        symbol: str,
        bars: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        """Return a fresh :class:`Proposal` or ``None`` for "no signal".

        ``None`` is the canonical no-op path; the service records no
        ``trade_proposals`` row + emits structlog
        ``trading.strategy.no_signal`` for observability.

        **No-lookahead invariant**: ``bars`` carries the full history up
        to (but not including) ``now``. Strategies MAY inspect any
        subset; they MUST NOT call ``datetime.now()`` or otherwise peek
        at future data. T3's property tests verify the invariant by
        running each strategy against pairs of histories that differ
        only in their post-``now`` suffix and asserting the proposal is
        identical.
        """
        ...


@runtime_checkable
class MarketDataPort(Protocol):
    """Read-only port for fetching historical bars (slice T4-followup-market-data).

    Production daemons use ``DBMarketDataAdapter`` (reads from the
    ``market_data_bars`` table populated by the IBKR ingestor). Tests
    use ``InMemoryMarketDataAdapter`` (seeded synthetic bars). The
    daemon's read path is decoupled from the IBKR connection — bars
    are populated asynchronously by the daily ``market_data_sync``
    cron routine OR the ``iguanatrader market-data sync`` CLI.
    """

    async def get_bars(
        self,
        *,
        symbol: str,
        timeframe: Literal["1d", "1h", "1m"],
        lookback_bars: int,
        as_of: datetime | None = None,
    ) -> BarHistory:
        """Return the last ``lookback_bars`` bars sorted ascending by ``ts``.

        ``as_of`` (slice market-data-replay): when set, filters bars to
        ``ts <= as_of`` before applying the lookback window. Backwards-
        compatible: ``None`` returns the latest bars (current behavior).

        Raises ``MarketDataNotAvailableError`` if zero bars exist for
        the (tenant, symbol, timeframe) tuple. Callers handle by
        logging + skipping the symbol (FR isolation).
        """
        ...


# ----------------------------------------------------------------------
# Deterministic client_order_id (audit #7)
# ----------------------------------------------------------------------

#: Fixed UUIDv5 namespace for client_order_id derivation. Frozen forever —
#: changing it would re-key every order's idempotency identity and defeat
#: broker-side dedup across an app upgrade.
_CLIENT_ORDER_ID_NAMESPACE = UUID("c1d0a7de-0000-4000-8000-000000000007")


def derive_client_order_id(tenant_id: UUID, role: str, *parts: object) -> UUID:
    """Derive a deterministic ``client_order_id`` for a logical order.

    Audit #7: a timed-out or reconnect-retried submission of the SAME
    logical order (same proposal for an entry; same trade for an exit)
    MUST carry the SAME ``client_order_id`` so the broker adapter dedupes
    the re-submission instead of doubling the position. UUIDv5 over a fixed
    namespace + the order's logical identity gives that determinism without
    persisting a mapping table.

    ``role`` discriminates entry vs exit so an entry and a later exit on the
    same trade never collide on the per-tenant UNIQUE constraint.
    """
    seed = ":".join((str(tenant_id), role, *(str(p) for p in parts)))
    return uuid5(_CLIENT_ORDER_ID_NAMESPACE, seed)


__all__ = [
    "Bar",
    "BarHistory",
    "BrokerOrderId",
    "BrokerPort",
    "EquitySnapshotValue",
    "FillEvent",
    "MarketDataPort",
    "NewOrder",
    "Position",
    "Proposal",
    "StrategyConfigSnapshot",
    "StrategyPort",
    "WorkingOrder",
    "derive_client_order_id",
]
