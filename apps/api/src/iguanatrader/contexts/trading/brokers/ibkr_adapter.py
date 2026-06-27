"""IBKR broker adapter — :class:`BrokerPort` over the :class:`IBClient` Protocol.

Per slice T2 design D2-D6:

* Composes :class:`HeartbeatMixin` (slice 2) — 30s heartbeat against
  TWS via ``client.req_current_time()`` with 90s deadline (NFR-P8).
* Idempotent :meth:`place_order` keyed by :attr:`NewOrder.client_order_id`
  (NFR-I1) — re-submitting the same client_order_id after a partial-
  network drop returns the cached :type:`BrokerOrderId` without a
  second broker submission.
* Reconciliation-on-reconnect — diffs ``client.req_all_open_orders()``
  + ``client.req_executions(since=last_disconnect)`` against the local
  ``orders`` + ``fills`` rows; emits ``broker.fill.catchup`` events for
  unobserved fills (FR16 + NFR-R2).
* Resilient reconnect loop — wraps :meth:`HeartbeatMixin.reconnect_loop`
  with a 5-attempt ceiling. Exhausting the canonical
  ``[3, 6, 12, 24, 48]`` sequence publishes
  :class:`RiskKillSwitchActivated(source="automatic_backoff")` and
  stops further attempts (NFR-R7).
* Auth failure short-circuits — if the IB client raises an auth error,
  the loop publishes the killswitch immediately without consuming
  backoff sleeps.

The adapter is :class:`BrokerPort`-compatible structurally — mypy
verifies via the Protocol. The :class:`IBClient` Protocol abstracts
``ib_async`` so the adapter is testable with the in-tree fake at
``apps/api/tests/_fakes/ib_async_fake.py`` and production wiring is
deferred to a deployment slice.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from iguanatrader.contexts.trading.brokers.client_protocol import (
    Contract,
    IBClient,
    IBOrder,
)
from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import (
    IBKRBrokerageModel,
    translate_order_type,
)
from iguanatrader.contexts.trading.ports import (
    BrokerOrderId,
    EquitySnapshotValue,
    FillEvent,
    NewOrder,
    Position,
    WorkingOrder,
    derive_client_order_id,
)
from iguanatrader.shared.backoff import backoff_seconds
from iguanatrader.shared.errors import IntegrationError
from iguanatrader.shared.heartbeat import ConnectionState, HeartbeatMixin
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from iguanatrader.shared.messagebus import MessageBus

logger = logging.getLogger(__name__)


#: Heartbeat cadence — one ping every 30s per NFR-P8.
DEFAULT_HEARTBEAT_INTERVAL_SECONDS: float = 30.0
#: Per-ping deadline — 90s per NFR-P8 (TWS occasionally takes ≥30s on cold
#: starts; 90s leaves headroom while still detecting a stuck connection).
DEFAULT_HEARTBEAT_TIMEOUT_SECONDS: float = 90.0
#: Reconnect attempt ceiling — after 5 failures the killswitch trips.
MAX_RECONNECT_ATTEMPTS: int = 5
#: Reconciliation window cap — IBKR's reqExecutions does not surface
#: history beyond ~7 days reliably.
RECONCILIATION_WINDOW_DAYS: int = 7

#: IBKR order statuses that are NOT live/working — :meth:`list_working_orders`
#: drops these so the position-review read model only sees orders actually
#: resting at the broker. Everything else ("PreSubmitted", "Submitted",
#: "PendingSubmit", "ApiPending", "PendingCancel", …) is treated as working.
_TERMINAL_ORDER_STATUSES: frozenset[str] = frozenset(
    {"Filled", "Cancelled", "ApiCancelled", "Inactive"}
)

#: Auth-failure marker — :meth:`_connect_client` raises
#: :class:`BrokerAuthError` when the TWS handshake fails on credentials.
#: The reconnect loop pattern-matches on the type to short-circuit retries.
AUTH_FAILURE_TYPE_URI = "urn:iguanatrader:error:broker-auth-failed"
RECONNECT_EXHAUSTED_TYPE_URI = "urn:iguanatrader:error:broker-reconnect-exhausted"
WINDOW_EXHAUSTED_TYPE_URI = "urn:iguanatrader:error:broker-window-exhausted"


class BrokerAuthError(IntegrationError):
    """IBKR rejected the credentials at TWS/Gateway connect time."""

    type_uri = AUTH_FAILURE_TYPE_URI
    default_title = "Broker Authentication Failed"
    default_status = 502


class BrokerWindowExhaustedError(IntegrationError):
    """``reconcile_fills`` window > 7 days — IBKR can't surface that history."""

    type_uri = WINDOW_EXHAUSTED_TYPE_URI
    default_title = "Broker Reconciliation Window Exhausted"
    default_status = 422


class IBKRAdapter(HeartbeatMixin):
    """Sync :class:`BrokerPort` implementation against an :class:`IBClient`."""

    def __init__(
        self,
        *,
        brokerage: IBKRBrokerageModel,
        client_factory: Callable[[], IBClient],
        bus: MessageBus | None = None,
        tenant_id: UUID | None = None,
        native_bracket: bool = False,
    ) -> None:
        super().__init__()
        self._brokerage = brokerage
        self._client_factory = client_factory
        self._bus = bus
        self._tenant_id = tenant_id
        self._native_bracket = native_bracket
        self._client: IBClient | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._shutting_down: bool = False
        self._last_disconnect_at: datetime | None = None
        # Cache of (client_order_id, broker_order_id) for in-process
        # idempotency. Persistence-layer dedupe is the canonical path
        # (T4 wires the ``orders`` table); this cache is the
        # short-circuit for the common "same place_order called twice
        # in the same session" case.
        self._client_order_cache: dict[UUID, BrokerOrderId] = {}
        # Cache of Execution.exec_id we've already emitted as
        # FillEvent — drives reconciliation idempotency.
        self._known_exec_ids: set[str] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the broker connection + start heartbeat loop."""
        await self._connect_client()
        self.mark_connected()
        await self._emit_event(
            "broker.connection.established",
            {"mode": self._brokerage.mode, "host": self._brokerage.host},
        )
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="ibkr.heartbeat")

    async def disconnect(self) -> None:
        """Tear down the connection. Idempotent."""
        self._shutting_down = True
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.disconnect()  # Best-effort; connection going away.
        await self.mark_disconnected()

    # ------------------------------------------------------------------
    # Ephemeral live-gateway connect-on-demand (WS-4 / WS-F)
    # ------------------------------------------------------------------

    async def ensure_connected(self) -> None:
        """(Re)establish + VERIFY a connection on demand — the ephemeral path.

        The ephemeral live model keeps the IBKR gateway DOWN between approved
        order batches (a live gateway logs the owner out of the mobile app), so
        the daemon must NOT hold a persistent connection or run the background
        heartbeat/reconnect loop: an intentional gateway-down period would
        otherwise walk :meth:`_resilient_reconnect_loop` to exhaustion and trip
        the kill-switch. Instead the gateway coordinator calls this right after a
        lease is confirmed ready, to connect at the only moment it matters —
        immediately before a real-money order.

        Idempotent within a live window: if already CONNECTED, one heartbeat
        ping confirms the socket is still alive and the call returns without
        reconnecting. A stale/half-open socket (ping fails) or a connection torn
        down with the gateway between leases is cleaned up and reconnected
        against the freshly-leased gateway. The new connection is verified with a
        heartbeat BEFORE it is trusted; any failure tears the connection back
        down and RAISES so the caller fails CLOSED (no live order is placed).

        Unlike :meth:`connect`, this starts NO persistent heartbeat task — the
        ephemeral path verifies liveness on demand here, never in the background,
        so a deliberately-down gateway can never escalate to the kill-switch.
        """
        if self._shutting_down:
            raise IntegrationError(detail="IBKRAdapter.ensure_connected: adapter is shutting down")
        if self._state is ConnectionState.CONNECTED and self._client is not None:
            try:
                await self._send_heartbeat()
                return
            except Exception:
                # Stale / half-open socket (gateway recycled under us) — fall
                # through to a clean reconnect against the fresh lease.
                logger.info("ibkr.adapter.ensure_connected.stale_socket_reconnecting")
        await self._teardown_connection()
        await self._connect_client()
        try:
            await self._send_heartbeat()  # verify BEFORE trusting it with money
        except Exception:
            await self._teardown_connection()
            raise
        self.mark_connected()
        await self._emit_event(
            "broker.connection.established",
            {"mode": self._brokerage.mode, "host": self._brokerage.host, "ephemeral": True},
        )

    async def _teardown_connection(self) -> None:
        """Drop the current connection WITHOUT shutting the adapter down.

        Used by the ephemeral :meth:`ensure_connected` path to recycle a stale or
        torn-down connection between leases. Cancels any heartbeat/reconnect
        tasks (defensive — the ephemeral path starts none), best-effort
        disconnects the client, and resets to DISCONNECTED. Unlike
        :meth:`disconnect` it does NOT set ``_shutting_down`` (so the next lease
        can reconnect) and does NOT fire :meth:`_on_disconnect` — the gateway
        going down between leases is INTENTIONAL, not a connection loss to alert
        on or to seed reconciliation from.
        """
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.disconnect()
            self._client = None
        self._state = ConnectionState.DISCONNECTED

    async def _connect_client(self) -> None:
        """Construct + connect a fresh :class:`IBClient`.

        Raises :class:`IntegrationError(type_uri=AUTH_FAILURE_TYPE_URI)`
        when the broker rejects credentials. Other exceptions propagate
        (network errors get retried by the reconnect loop).
        """
        self._client = self._client_factory()
        try:
            await self._client.connect_async(
                self._brokerage.host,
                self._brokerage.port,
                self._brokerage.client_id,
            )
        except _IBAuthError as exc:
            raise BrokerAuthError(
                detail=f"IBKR authentication failed: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # HeartbeatMixin overrides
    # ------------------------------------------------------------------

    async def _send_heartbeat(self) -> None:
        if self._client is None:
            raise IntegrationError(detail="IBKRAdapter._send_heartbeat: client is None")
        async with asyncio.timeout(DEFAULT_HEARTBEAT_TIMEOUT_SECONDS):
            await self._client.req_current_time()

    async def _on_disconnect(self) -> None:
        self._last_disconnect_at = utc_now()
        try:
            await self._emit_event(
                "broker.connection.lost",
                {"mode": self._brokerage.mode, "at": self._last_disconnect_at.isoformat()},
            )
        except Exception:
            logger.warning("ibkr.adapter._on_disconnect.event_emit_failed", exc_info=True)

    async def _heartbeat_loop(self) -> None:
        """Send heartbeats every ``DEFAULT_HEARTBEAT_INTERVAL_SECONDS`` seconds.

        On failure: marks disconnected (fires _on_disconnect once) +
        kicks the resilient reconnect loop as a background task + returns.
        Designed to be wrapped in :meth:`asyncio.create_task` and
        cancelled on :meth:`disconnect`.
        """
        while not self._shutting_down:
            try:
                await asyncio.sleep(DEFAULT_HEARTBEAT_INTERVAL_SECONDS)
                await self._send_heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._shutting_down:
                    return
                await self.mark_disconnected()
                self._reconnect_task = asyncio.create_task(
                    self._resilient_reconnect_loop(), name="ibkr.reconnect"
                )
                return

    # ------------------------------------------------------------------
    # Resilient reconnect with kill-switch escalation
    # ------------------------------------------------------------------

    async def _resilient_reconnect_loop(self) -> None:
        """Walk the canonical backoff sequence, capped at 5 attempts."""
        # Mirror HeartbeatMixin.reconnect_loop: declare RECONNECTING before
        # the first attempt so observers + assertions see the in-flight
        # state. If all attempts fail, state stays RECONNECTING (killswitch
        # is the outward signal). On success, mark_connected flips it.
        self.mark_reconnecting()
        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            delay = backoff_seconds(attempt, with_jitter=True)
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise

            try:
                await self._connect_client()
            except BrokerAuthError as exc:
                # Auth failure short-circuits — credentials won't fix
                # themselves on retry. Trip the killswitch immediately.
                await self._emit_killswitch(
                    reason="ibkr.adapter.auth_failed",
                    metadata={"attempt": attempt + 1, "error": str(exc)},
                )
                return
            except IntegrationError as exc:
                await self._emit_event(
                    "broker.connection.attempt_failed",
                    {"attempt": attempt + 1, "delay_seconds": delay, "error": str(exc)},
                )
                continue
            except Exception as exc:
                await self._emit_event(
                    "broker.connection.attempt_failed",
                    {"attempt": attempt + 1, "delay_seconds": delay, "error": str(exc)},
                )
                continue

            # Connection succeeded — verify by sending a heartbeat, then
            # restore state machine + run reconciliation.
            try:
                await self._send_heartbeat()
            except Exception as exc:
                await self._emit_event(
                    "broker.connection.attempt_failed",
                    {"attempt": attempt + 1, "delay_seconds": delay, "error": str(exc)},
                )
                continue

            self.mark_connected()
            await self._emit_event(
                "broker.connection.restored",
                {"attempt": attempt + 1, "mode": self._brokerage.mode},
            )
            await self._post_reconnect_reconciliation()
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(), name="ibkr.heartbeat"
            )
            return

        # All attempts exhausted — trip the killswitch.
        await self._emit_killswitch(
            reason="ibkr.adapter.reconnect_exhausted",
            metadata={
                "attempts": MAX_RECONNECT_ATTEMPTS,
                "backoff_sequence": [3, 6, 12, 24, 48],
            },
        )

    # ------------------------------------------------------------------
    # BrokerPort: place_order + cancel_order + get_position + get_account_equity
    # ------------------------------------------------------------------

    @property
    def native_bracket_enabled(self) -> bool:
        """True when the feature-flagged native bracket/OCO path is active.

        The service reads this (best-effort via ``getattr``) to know the broker
        will attach protective child legs — STP + optional LMT — at submit
        time, so it can persist the matching exit Order rows keyed by the same
        derived ``client_order_id`` the adapter stamps on each child leg.
        """
        return self._native_bracket

    async def place_order(self, order: NewOrder) -> BrokerOrderId:
        """Submit ``order`` to IBKR. Idempotent against ``client_order_id``."""
        # Translate the domain order-type (lowercase ``market``/``limit``/…
        # stored on the ORM row) into the IBKR code the whitelist + the
        # ib_async translator expect, then gate on the translated value.
        ib_order_type = translate_order_type(order.order_type)
        self._brokerage.assert_supports_order_type(ib_order_type)
        if order.client_order_id is None:
            raise ValueError(
                "IBKRAdapter.place_order requires NewOrder.client_order_id "
                "(slice T2 NFR-I1 idempotency contract)."
            )
        cached = self._client_order_cache.get(order.client_order_id)
        if cached is not None:
            logger.info(
                "broker.order.idempotent_replay",
                extra={
                    "client_order_id": str(order.client_order_id),
                    "broker_order_id": cached,
                },
            )
            return cached
        if self._client is None:
            raise IntegrationError(detail="IBKRAdapter.place_order: client not connected")

        contract = self._build_contract(order.symbol)

        # Native bracket/OCO path (feature-flagged via constructor, default
        # OFF). When ON and the order carries a protective stop, submit the
        # entry as a broker-side bracket — parent entry + child STP (+ optional
        # LMT take-profit) transmitted atomically with parentId/OCA linkage, so
        # the stop rests AT THE BROKER even if the daemon dies. When OFF (or no
        # stop), fall through to the unchanged single-order path below.
        if self._native_bracket and order.stop_price is not None:
            reverse = "SELL" if order.side.upper() == "BUY" else "BUY"
            parent = self._build_ib_order(order, ib_order_type=ib_order_type)
            # Stamp each child leg with a DETERMINISTIC client_order_id (a valid
            # UUID, not a ``<entry>:stop`` suffix). IBKR echoes this back as the
            # execution ``order_ref`` when the leg fills; ``_order_id_from_ref``
            # parses it straight to the matching exit Order row the service
            # persisted under the SAME derived id, so the close-flow records a
            # real exit price + P&L. The suffix scheme failed ``UUID(...)`` →
            # zero id → the exit fill was silently dropped (``order_missing``).
            stop_child_ref = str(
                derive_client_order_id(order.tenant_id, "bracket_stop", order.client_order_id)
            )
            tp_child_ref = str(
                derive_client_order_id(order.tenant_id, "bracket_tp", order.client_order_id)
            )
            stop_loss = IBOrder(
                action=reverse,
                total_quantity=order.quantity,
                order_type="STP",
                aux_price=order.stop_price,
                account=self._brokerage.account_code,
                order_ref=stop_child_ref,
            )
            take_profit: IBOrder | None = None
            if order.target_price is not None:
                take_profit = IBOrder(
                    action=reverse,
                    total_quantity=order.quantity,
                    order_type="LMT",
                    limit_price=order.target_price,
                    account=self._brokerage.account_code,
                    order_ref=tp_child_ref,
                )
            broker_order_id_raw = await self._client.place_bracket_order(
                contract, parent, stop_loss, take_profit
            )
            broker_order_id = BrokerOrderId(broker_order_id_raw)
            self._client_order_cache[order.client_order_id] = broker_order_id
            await self._emit_event(
                "broker.order.bracket_placed",
                {
                    "client_order_id": str(order.client_order_id),
                    "broker_order_id": broker_order_id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "quantity": str(order.quantity),
                    "stop_price": str(order.stop_price),
                    "target_price": (
                        str(order.target_price) if order.target_price is not None else None
                    ),
                },
            )
            return broker_order_id

        ib_order = self._build_ib_order(order, ib_order_type=ib_order_type)
        broker_order_id_raw = await self._client.place_order(contract, ib_order)
        broker_order_id = BrokerOrderId(broker_order_id_raw)
        self._client_order_cache[order.client_order_id] = broker_order_id
        await self._emit_event(
            "broker.order.placed",
            {
                "client_order_id": str(order.client_order_id),
                "broker_order_id": broker_order_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": str(order.quantity),
                "order_type": order.order_type,
            },
        )
        return broker_order_id

    async def cancel_order(self, broker_order_id: BrokerOrderId) -> None:
        if self._client is None:
            raise IntegrationError(detail="IBKRAdapter.cancel_order: client not connected")
        await self._client.cancel_order(str(broker_order_id))
        await self._emit_event(
            "broker.order.cancel_requested",
            {"broker_order_id": broker_order_id},
        )

    async def get_position(self, symbol: str) -> Position:
        if self._client is None:
            raise IntegrationError(detail="IBKRAdapter.get_position: client not connected")
        positions = await self._client.positions()
        for pos in positions:
            if pos.symbol == symbol:
                return Position(
                    tenant_id=self._tenant_id_or_zero(),
                    symbol=symbol,
                    quantity=pos.quantity,
                    average_price=pos.average_cost,
                    unrealized_pnl=pos.unrealized_pnl,
                    currency=pos.currency,
                )
        return Position(
            tenant_id=self._tenant_id_or_zero(),
            symbol=symbol,
            quantity=Decimal("0"),
            average_price=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            currency="USD",
        )

    async def list_positions(self) -> list[Position]:
        if self._client is None:
            raise IntegrationError(detail="IBKRAdapter.list_positions: client not connected")
        raw = await self._client.positions()
        out: list[Position] = []
        for pos in raw:
            if pos.quantity == 0:
                continue
            out.append(
                Position(
                    tenant_id=self._tenant_id_or_zero(),
                    symbol=pos.symbol,
                    quantity=pos.quantity,
                    average_price=pos.average_cost,
                    unrealized_pnl=pos.unrealized_pnl,
                    currency=pos.currency,
                )
            )
        return out

    async def get_account_equity(self) -> EquitySnapshotValue:
        if self._client is None:
            raise IntegrationError(detail="IBKRAdapter.get_account_equity: client not connected")
        rows = await self._client.account_summary()
        tags: dict[str, Decimal] = {}
        currency = "USD"
        for row in rows:
            tags[row.tag] = row.value
            currency = row.currency
        return EquitySnapshotValue(
            tenant_id=self._tenant_id_or_zero(),
            mode=self._brokerage.mode,
            account_equity=tags.get("NetLiquidation", Decimal("0")),
            cash_balance=tags.get("TotalCashValue", Decimal("0")),
            realized_pnl_today=tags.get("RealizedPnL", Decimal("0")),
            unrealized_pnl=tags.get("UnrealizedPnL", Decimal("0")),
            currency=currency,
            snapshot_kind="event",
            captured_at=utc_now(),
        )

    async def list_working_orders(self) -> list[WorkingOrder]:
        """Return every order currently resting/working at the broker.

        Slice ``position-review-broker-visibility``: read-only translation
        of the IBKR open-order book into domain :class:`WorkingOrder`s,
        surfacing the stop trigger (``auxPrice``) as
        :attr:`WorkingOrder.stop_price` so the position-review read model
        can see the protective stop level that ``limit_price`` (``lmtPrice``)
        does not carry for a plain stop. Filled / cancelled rows the broker
        may still echo are dropped — only live working states are returned.
        """
        if self._client is None:
            raise IntegrationError(detail="IBKRAdapter.list_working_orders: client not connected")
        raw = await self._client.req_all_open_orders()
        out: list[WorkingOrder] = []
        for o in raw:
            if o.status in _TERMINAL_ORDER_STATUSES:
                continue
            out.append(
                WorkingOrder(
                    tenant_id=self._tenant_id_or_zero(),
                    symbol=o.symbol,
                    action=o.action,
                    quantity=o.total_quantity,
                    order_type=o.order_type,
                    limit_price=o.limit_price,
                    stop_price=o.aux_price,
                    order_ref=o.order_ref,
                    status=o.status,
                )
            )
        return out

    # ------------------------------------------------------------------
    # BrokerPort: reconcile_fills (post-disconnect catch-up)
    # ------------------------------------------------------------------

    async def reconcile_fills(self, since: datetime) -> AsyncIterator[FillEvent]:
        """Yield every fill recorded after ``since``.

        Caller-driven catch-up path; the adapter's internal
        :meth:`_post_reconnect_reconciliation` consumes the same
        underlying broker call but emits structured catchup events
        rather than yielding directly.
        """
        async for ev in self._reconcile_fills_async(since):
            yield ev

    async def _reconcile_fills_async(self, since: datetime) -> AsyncIterator[FillEvent]:
        if self._client is None:
            raise IntegrationError(detail="IBKRAdapter.reconcile_fills: client not connected")
        if utc_now() - since > timedelta(days=RECONCILIATION_WINDOW_DAYS):
            raise BrokerWindowExhaustedError(
                detail=(
                    f"reconcile_fills window > {RECONCILIATION_WINDOW_DAYS} days; "
                    "IBKR reqExecutions does not surface history that old reliably"
                ),
            )
        executions = await self._client.req_executions(since)
        for execution in executions:
            yield FillEvent(
                tenant_id=self._tenant_id_or_zero(),
                order_id=self._order_id_from_ref(execution.order_ref),
                quantity_filled=execution.shares,
                fill_price=execution.price,
                commission=execution.commission,
                commission_currency=execution.commission_currency,
                filled_at=execution.time,
                broker_fill_id=execution.exec_id,
            )

    async def _post_reconnect_reconciliation(self) -> None:
        """Diff broker state vs local cache; emit catchup events."""
        if self._last_disconnect_at is None:
            return
        if self._client is None:
            return
        executions = await self._client.req_executions(self._last_disconnect_at)
        for execution in executions:
            if execution.exec_id in self._known_exec_ids:
                continue
            self._known_exec_ids.add(execution.exec_id)
            await self._emit_event(
                "broker.fill.catchup",
                {
                    "exec_id": execution.exec_id,
                    "perm_id": execution.perm_id,
                    "order_ref": execution.order_ref,
                    "symbol": execution.symbol,
                    "shares": str(execution.shares),
                    "price": str(execution.price),
                    "commission": str(execution.commission),
                    "filled_at": execution.time.isoformat(),
                },
            )
        # State drift: open orders the broker has that we don't track
        # locally (T4 wires the orders table comparison; here we just
        # surface the broker view as an event consumers can subscribe).
        open_orders = await self._client.req_all_open_orders()
        for open_order in open_orders:
            await self._emit_event(
                "broker.order.state_observed",
                {
                    "perm_id": open_order.perm_id,
                    "order_ref": open_order.order_ref,
                    "symbol": open_order.symbol,
                    "status": open_order.status,
                    "total_quantity": str(open_order.total_quantity),
                },
            )

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _build_contract(self, symbol: str) -> Contract:
        # WS-3: resolve exchange/currency per symbol (UCITS symbols trade in
        # GBP/EUR). Defaults to SMART/USD so the US watchlist is unchanged.
        from iguanatrader.contexts.trading.brokers.symbol_contract import (
            resolve_contract_params,
        )

        params = resolve_contract_params(symbol)
        return Contract(
            symbol=symbol,
            exchange=params.exchange,
            currency=params.currency,
            sec_type="STK",
            con_id=params.con_id,
        )

    def _build_ib_order(self, order: NewOrder, *, ib_order_type: str | None = None) -> IBOrder:
        # ``ib_order_type`` is the already-translated IBKR code from
        # :meth:`place_order`; fall back to translating here so direct
        # callers/tests still get the mapping.
        resolved_type = ib_order_type or translate_order_type(order.order_type)
        return IBOrder(
            action=order.side.upper(),
            total_quantity=order.quantity,
            order_type=resolved_type,
            limit_price=order.limit_price,
            aux_price=order.stop_price,
            account=self._brokerage.account_code,
            order_ref=str(order.client_order_id) if order.client_order_id else None,
            algo_kind=order.algo_kind,
        )

    def _order_id_from_ref(self, order_ref: str | None) -> UUID:
        """Parse the ``order_ref`` string back into the iguanatrader order UUID.

        Adapter uses ``str(NewOrder.client_order_id)`` as the IBKR
        ``orderRef`` when placing; reconciliation reverses it.
        """
        if order_ref is None:
            return UUID(int=0)
        try:
            return UUID(order_ref)
        except ValueError:
            return UUID(int=0)

    def _tenant_id_or_zero(self) -> UUID:
        return self._tenant_id if self._tenant_id is not None else UUID(int=0)

    # ------------------------------------------------------------------
    # Event emission helpers
    # ------------------------------------------------------------------

    async def _emit_event(
        self,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        """Structlog-narrate + (if a bus is wired) publish a generic dict event.

        Slice T2 keeps the bus surface simple; downstream consumers
        (T4 for orders, K1 for killswitch) subscribe by event name.
        """
        logger.info(event_name, extra=payload)
        if self._bus is None:
            return
        # Late import to avoid the slice-2 messagebus dep at module load
        # (keeps the trading.brokers package importable without the bus).
        from iguanatrader.shared.messagebus import Event

        @event_dataclass
        class _GenericEvent(Event):
            channel = event_name

        ev = _GenericEvent()
        await self._bus.publish(ev)

    async def _emit_killswitch(
        self,
        *,
        reason: str,
        metadata: dict[str, Any],
    ) -> None:
        """Publish a killswitch-equivalent event (slice K1 wires the canonical handler)."""
        await self._emit_event(
            "broker.killswitch.requested",
            {"reason": reason, **metadata},
        )
        if self._bus is None:
            return
        # K1 ships RiskKillSwitchActivated via the risk service; here we
        # publish a slim trigger event that K1's service subscribes
        # to. The full RiskKillSwitchActivated flow lands when T4
        # wires risk service consumption — design D5 deferred.
        from iguanatrader.contexts.risk.events import RiskKillSwitchActivated

        ev = RiskKillSwitchActivated(
            tenant_id=self._tenant_id_or_zero(),
            event_id=uuid4(),
            source="automatic_backoff",
            actor_user_id=None,
            reason=f"{reason}: {metadata}",
            occurred_at=utc_now(),
        )
        await self._bus.publish(ev)


# ----------------------------------------------------------------------
# Auth-failure marker (raised by the in-tree fake; production wiring
# pattern-matches on ``ib_async``-specific exception types here).
# ----------------------------------------------------------------------


class _IBAuthError(Exception):
    """Raised by the in-tree fake / production wrapper on credential failure.

    Adapter pattern-matches on the type to decide auth-failure short-
    circuit vs network-error retry. Production wiring (deployment
    slice) maps ``ib_async``'s specific auth exception classes here.
    """


def event_dataclass(cls: type) -> type:
    """Identity decorator — placeholder for future bus event-class wiring.

    Slice T2 publishes structured events but doesn't yet require the
    full bus channel routing surface. Stubbed so future K1/T4 wiring
    can swap to a real ``@dataclass`` + channel-name registration.
    """
    return cls


__all__ = [
    "AUTH_FAILURE_TYPE_URI",
    "DEFAULT_HEARTBEAT_INTERVAL_SECONDS",
    "DEFAULT_HEARTBEAT_TIMEOUT_SECONDS",
    "MAX_RECONNECT_ATTEMPTS",
    "RECONCILIATION_WINDOW_DAYS",
    "RECONNECT_EXHAUSTED_TYPE_URI",
    "WINDOW_EXHAUSTED_TYPE_URI",
    "BrokerAuthError",
    "BrokerWindowExhaustedError",
    "IBKRAdapter",
]
