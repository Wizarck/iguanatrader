"""TradingService — orchestrator skeleton for the propose→fills sequence.

Per design D2: inter-step communication is via :class:`MessageBus`
events, NOT direct method calls to :class:`RiskService` /
:class:`ApprovalService`. The sequence:

1. :meth:`propose` — call ``StrategyPort.evaluate``, persist
   ``trade_proposals`` row, publish :class:`ProposalCreated`.
2. K1 ``RiskService`` subscribes to :class:`ProposalCreated`, evaluates,
   publishes :class:`ProposalRiskEvaluated`.
3. T1 :meth:`risk_check_handler` (subscribed to
   :class:`ProposalRiskEvaluated`) decides whether to publish
   :class:`ApprovalRequested`.
4. P1 ``ApprovalService`` dispatches the human-in-the-loop request,
   publishes :class:`ProposalApproved` or :class:`ProposalRejected`.
5. T1 :meth:`execute_on_approval_handler` (subscribed to
   :class:`ProposalApproved`) calls ``BrokerPort.place_order``,
   persists an ``orders`` row, publishes :class:`OrderPlaced`.
6. T1 :meth:`reconcile_fills_handler` (subscribed to broker fills)
   persists ``fills`` rows + updates ``trades.state``, publishes
   :class:`OrderFilled`.

Slice T1 plants the wiring; only :meth:`propose` has a non-trivial
body. Other handlers are skeletal — they emit a structlog breadcrumb +
have ``# T4 fills`` comments.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog

from iguanatrader.contexts.observability.errors import BudgetExceededError
from iguanatrader.contexts.trading.brokers.ibkr_adapter import BrokerAuthError
from iguanatrader.contexts.trading.events import (
    ApprovalRequested,
    CloseTradeRequested,
    EquityUpdated,
    OrderFilled,
    OrderPlaced,
    OrderRejected,
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    ProposalRiskEvaluated,
    TradeClosed,
)
from iguanatrader.contexts.trading.models import (
    EquitySnapshot,
    Fill,
    Order,
    Trade,
    TradeProposal,
)
from iguanatrader.contexts.trading.ports import (
    BarHistory,
    BrokerOrderId,
    BrokerPort,
    FillEvent,
    NewOrder,
    Proposal,
    StrategyConfigSnapshot,
    StrategyPort,
    derive_client_order_id,
)
from iguanatrader.contexts.trading.repository import (
    EquitySnapshotRepository,
    FillRepository,
    OrderRepository,
    TradeProposalRepository,
    TradeRepository,
)
from iguanatrader.shared.contextvars import (
    session_var,
    tenant_id_var,
    with_tenant_context,
)
from iguanatrader.shared.errors import IguanaError, IntegrationError
from iguanatrader.shared.messagebus import MessageBus
from iguanatrader.shared.time import now as utc_now

log = structlog.get_logger("iguanatrader.contexts.trading.service")


class KillSwitchActiveError(IguanaError):
    """Raised by :meth:`TradingService.propose` when the kill-switch is on.

    Slice K1 publishes ``KillSwitchTripped`` when the engine trips; T1
    sets an internal flag in :meth:`halt_handler`. ``propose`` checks
    the flag and refuses to emit a fresh proposal.

    The 503 is a stand-in until T4 finalises the runtime semantic; it
    matches the slice-5 :class:`BootstrapNotReadyError` precedent of
    "service-temporarily-unavailable Problem".
    """

    type_uri = "urn:iguanatrader:error:kill-switch-active"
    default_title = "Kill Switch Active"
    default_status = 503


class TradeNotClosableError(IguanaError):
    """Raised by :meth:`TradingService.close_trade` when the trade is not
    in a closable state.

    Slice ``trade-close-flow-exit-pathway``. A trade is closable only
    from ``state="open"``; ``"closing"`` means an exit order is
    already pending (idempotency — duplicate close requests are
    rejected to avoid double exits) and ``"closed"`` means the trade
    has already terminated. The 409 mirrors the standard HTTP
    convention for "valid request, current state forbids it".
    """

    type_uri = "urn:iguanatrader:error:trade-not-closable"
    default_title = "Trade Not Closable"
    default_status = 409


#: Valid ``reason`` values accepted by :meth:`TradingService.close_trade`.
#: Mirrors the ``ck_trades_exit_reason_allowed`` CHECK constraint enum
#: (migrations 0015 + 0030): ``stop`` (stop-loss hit), ``target`` (take-
#: profit hit), ``manual`` (operator-initiated close), ``expiry`` (option
#: expiry — not relevant to v1.5 equities but kept for forward-
#: compatibility with options contracts), ``ibkr_reconcile`` (slice
#: dual-daemon-followups Phase-2.5: reconcile detected the broker no
#: longer holds the position so the daemon closes the local row).
_VALID_EXIT_REASONS: frozenset[str] = frozenset(
    {"stop", "target", "manual", "expiry", "ibkr_reconcile"}
)


# Type alias for the strategy resolver callable injected at construction.
# Slice T4-followup-market-data: signature changed to async so production
# closures can do session-scoped DB lookups (StrategyConfigRepository.get_by_id).
# Tests that previously injected ``lambda id: mapping[id]`` need a 1-line
# wrapper: ``async def _resolve(id): return mapping[id]``.
StrategyResolver = Callable[[UUID], Awaitable[StrategyPort]]

# Reads the authoritative per-tenant kill-switch state (the DB cache that
# ``RiskService.evaluate_proposal`` consults). Injected so the trading
# context can re-check the kill switch at the broker-submission boundary
# without importing the risk persistence layer directly. ``True`` means
# halted. When unset, the execute path proceeds (legacy/test behaviour);
# the production daemon wires the real reader.
KillSwitchReader = Callable[[UUID], Awaitable[bool]]


class TradingService:
    """Orchestrate the propose→fills sequence via :class:`MessageBus`.

    Construction wiring:

    * ``bus``: in-process :class:`MessageBus` for inter-context events.
    * ``broker``: a :class:`BrokerPort` adapter (T2 ships the IBKR one;
      tests inject a fake).
    * ``strategy_resolver``: a callable that maps a
      ``strategy_config_id`` to the live :class:`StrategyPort` instance
      (T3 ships the manager that hot-reloads strategies on config bump;
      tests inject a static mapping).

    The session is read from
    :data:`iguanatrader.shared.contextvars.session_var` via
    :class:`BaseRepository` — the service does NOT take a session in
    its constructor (per slice-2 D2: domain code never threads sessions
    through call stacks).
    """

    def __init__(
        self,
        *,
        bus: MessageBus,
        broker: BrokerPort,
        strategy_resolver: StrategyResolver,
        execution_algo: str = "market",
        order_timeout_secs: float = 30.0,
        kill_switch_reader: KillSwitchReader | None = None,
    ) -> None:
        self._bus = bus
        self._broker = broker
        self._strategy_resolver = strategy_resolver
        # Slice #5: authoritative kill-switch re-check at the execute /
        # close broker-submission boundary. The in-memory
        # ``_kill_switch_active`` flag below is NOT load-bearing in
        # production (``halt_handler`` is unsubscribed), so the DB-backed
        # reader is the real gate that stops an already-approved proposal
        # from executing after the operator (or an auto-breach) halts.
        self._kill_switch_reader = kill_switch_reader
        # Slice ``ibkr-execution-algos-entry``: which IBKR execution
        # algorithm to attach to every entry order this service
        # submits. Canonical values match :class:`RiskCaps.execution_algo`
        # (``"market"`` / ``"adaptive"`` / ``"twap"``). Defaults to
        # ``"market"`` to preserve pre-slice behaviour for tests that
        # construct the service without specifying — production wiring
        # passes the operator-configured cap. The service treats this
        # as immutable per-instance; hot-reload of the cap requires a
        # new service construction (acceptable: the value sits in env
        # config, not a per-request decision).
        self._execution_algo = execution_algo
        # Slice ``order-timeout-restart-reconcile``: how long to wait
        # for ``broker.place_order`` (entry + exit submissions) before
        # bailing with a ``timeout`` rejection. Without this, a hung
        # IBKR socket can block the approval handler indefinitely and
        # back-pressure the message bus. 30 s comfortably covers the
        # IBKR algo path (Adaptive can take 5-10s on a normal day);
        # operator overrides via the env var
        # ``IGUANATRADER_ORDER_TIMEOUT_SECS`` when the upstream gateway
        # is known to be slower.
        self._order_timeout_secs = order_timeout_secs
        self._kill_switch_active: bool = False

    # ------------------------------------------------------------------
    # Subscription wiring
    # ------------------------------------------------------------------
    def register_subscriptions(self, bus: MessageBus | None = None) -> None:
        """Register MessageBus subscriptions for the inbound events.

        Idempotent only insofar as you call it once per service instance;
        re-registering creates new subscription handles. T4 owns the
        wiring of the daemon process that constructs one
        :class:`TradingService` per tenant + calls this method on
        startup.
        """
        target_bus = bus if bus is not None else self._bus
        target_bus.subscribe(ProposalRiskEvaluated, self.risk_check_handler)
        target_bus.subscribe(
            ProposalApproved,
            self.execute_on_approval_handler,
            idempotent=True,
        )
        target_bus.subscribe(ProposalRejected, self.proposal_rejected_handler)
        target_bus.subscribe(
            CloseTradeRequested,
            self.close_trade_handler,
            idempotent=True,
        )

    # ------------------------------------------------------------------
    # Step 1 — propose (concrete body; T1 owns)
    # ------------------------------------------------------------------
    async def propose(
        self,
        *,
        symbol: str,
        strategy_config_id: UUID,
        bars: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        """Run the strategy + persist + publish :class:`ProposalCreated`.

        Returns ``None`` if the strategy returned no signal (the
        canonical no-op path); no row is INSERTed and no event is
        published.

        Raises :class:`KillSwitchActiveError` if a prior
        ``KillSwitchTripped`` event flipped the internal halt flag.
        """
        if self._kill_switch_active:
            log.warning(
                "trading.service.halted",
                method="propose",
                symbol=symbol,
                strategy_config_id=str(strategy_config_id),
            )
            raise KillSwitchActiveError(detail="Kill switch is active; no new proposals accepted.")

        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            raise LookupError(
                "tenant_id_var must be set before TradingService.propose; "
                "call from a request scope or via with_tenant_context()"
            )

        strategy = await self._strategy_resolver(strategy_config_id)
        proposal = strategy.evaluate(symbol, bars, config)

        if proposal is None:
            log.info(
                "trading.strategy.no_signal",
                symbol=symbol,
                strategy_kind=strategy.name(),
                strategy_version=strategy.version(),
            )
            return None

        # Persist the trade_proposals row. Column types match the ORM
        # model exactly; the slice-3 tenant listener stamps tenant_id +
        # the slice-3 append-only listener accepts the INSERT (only
        # UPDATE/DELETE are blocked).
        from iguanatrader.shared.kernel import BaseRepository

        proposal_id = uuid4()
        # Inline session pull — :class:`BaseRepository` reads
        # ``session_var`` lazily; we need a raw session handle here for
        # the single INSERT. T4 may refactor to push this into the
        # ``TradeProposalRepository``.
        session = BaseRepository().session

        row = TradeProposal(
            id=proposal_id,
            tenant_id=tenant_id,
            strategy_config_id=strategy_config_id,
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=proposal.quantity,
            entry_price_indicative=proposal.entry_price_indicative,
            stop_price=proposal.stop_price,
            target_price=proposal.target_price,
            confidence_score=proposal.confidence_score,
            reasoning=proposal.reasoning,
            research_brief_id=proposal.research_brief_id,
            mode=proposal.mode,
            correlation_id=proposal.correlation_id,
        )
        session.add(row)

        await self._bus.publish(
            ProposalCreated(
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol=proposal.symbol,
                strategy_kind=strategy.name(),
                strategy_version=config.version,
                correlation_id=proposal.correlation_id,
            )
        )

        log.info(
            "trading.proposal.created",
            proposal_id=str(proposal_id),
            symbol=proposal.symbol,
            strategy_kind=strategy.name(),
            tenant_id=str(tenant_id),
            correlation_id=str(proposal.correlation_id),
        )
        return proposal

    # ------------------------------------------------------------------
    # Step 3 — risk_check_handler (skeleton; T4 fills logic)
    # ------------------------------------------------------------------
    async def risk_check_handler(self, event: ProposalRiskEvaluated) -> None:
        """Subscriber: on permissive risk outcome publish :class:`ApprovalRequested`.

        Slice T4 (§2.A): on ``event.outcome == "reject"`` publish
        :class:`ProposalRejected` so downstream consumers (P1 audit
        channels, O1 cost meter) record the dead-end. The
        ``trade_proposals`` row is NOT mutated — the table is strict-
        append-only; the bus event is the durable record.
        """
        log.info(
            "trading.proposal.risk_evaluated.received",
            proposal_id=str(event.proposal_id),
            outcome=event.outcome,
            tenant_id=str(event.tenant_id),
        )

        if event.outcome == "allow":
            await self._bus.publish(
                ApprovalRequested(
                    tenant_id=event.tenant_id,
                    proposal_id=event.proposal_id,
                    decision=event.outcome,
                )
            )
            log.info(
                "trading.approval.requested",
                proposal_id=str(event.proposal_id),
                decision=event.outcome,
            )
            return

        if event.outcome == "clip":
            # Slice #37: ``clip`` is plumbed through the event contract
            # (Decision.clip_quantity) but the execute path builds the
            # order at proposal_row.quantity — clip_quantity is dropped,
            # so approving a clip would execute at FULL size and breach
            # the very cap that asked to clip it. Until clip_quantity is
            # threaded end-to-end (ApprovalRequested -> ProposalApproved
            # -> NewOrder(min(quantity, clip_quantity))), fail SAFE by
            # rejecting rather than silently over-sizing.
            await self._bus.publish(
                ProposalRejected(
                    tenant_id=event.tenant_id,
                    proposal_id=event.proposal_id,
                    reason="risk_engine_clip_unsupported",
                )
            )
            log.warning(
                "trading.proposal.clip_unsupported",
                proposal_id=str(event.proposal_id),
                tenant_id=str(event.tenant_id),
                clip_quantity=(
                    str(event.clip_quantity) if event.clip_quantity is not None else None
                ),
            )
            return

        if event.outcome == "reject":
            reason = (
                f"risk_engine_reject:{event.cap_type_breached}"
                if event.cap_type_breached
                else "risk_engine_reject"
            )
            await self._bus.publish(
                ProposalRejected(
                    tenant_id=event.tenant_id,
                    proposal_id=event.proposal_id,
                    reason=reason,
                )
            )
            log.info(
                "trading.proposal.rejected_by_risk",
                proposal_id=str(event.proposal_id),
                reason=reason,
                tenant_id=str(event.tenant_id),
            )

    # ------------------------------------------------------------------
    # Step 5 — execute_on_approval_handler (skeleton; T4 fills logic)
    # ------------------------------------------------------------------
    async def execute_on_approval_handler(self, event: ProposalApproved) -> None:
        """Subscriber: on :class:`ProposalApproved` call ``BrokerPort.place_order``.

        Idempotent at the bus boundary (slice 2 D1: subscribe with
        ``idempotent=True``); the registration in
        :meth:`register_subscriptions` sets the flag. T4 §2.B layers
        a second-line idempotency check via the
        :meth:`OrderRepository.get_by_proposal_id` lookup before
        contacting the broker.

        Sequence (per slice T4 design §2.1.2):

        1. Idempotency: skip if ``orders`` already has a row for the proposal.
        2. Load :class:`TradeProposal` (publish :class:`ProposalRejected` if missing).
        3. Create :class:`Trade` row (state='open').
        4. Build :class:`NewOrder` from the proposal.
        5. Submit via broker; map ``BrokerAuthError`` / ``BudgetExceededError`` to
           :class:`OrderRejected` + persist Order(state='rejected').
        6. On success: persist Order(state='submitted') + publish :class:`OrderPlaced`.
        """
        log.info(
            "trading.proposal.approved.received",
            proposal_id=str(event.proposal_id),
            tenant_id=str(event.tenant_id),
        )

        order_repo = OrderRepository()
        existing = await order_repo.get_by_proposal_id(event.proposal_id)
        if existing is not None:
            log.info(
                "trading.execute.idempotent_skip",
                proposal_id=str(event.proposal_id),
                order_id=str(existing.id),
                reason="order_already_placed",
            )
            return

        # Slice #5: authoritative kill-switch re-check BEFORE creating any
        # Trade/Order or contacting the broker. Closes the race where a
        # proposal was approved just before the operator/auto-breach
        # tripped the switch — without this gate the approval flows
        # straight to a live order. No Trade/Order row is created on the
        # halted path (nothing to orphan); the bus event is the record.
        if await self._is_halted(event.tenant_id):
            await self._bus.publish(
                OrderRejected(
                    tenant_id=event.tenant_id,
                    proposal_id=event.proposal_id,
                    reason="kill_switch",
                )
            )
            log.warning(
                "trading.execute.kill_switch_active",
                proposal_id=str(event.proposal_id),
                tenant_id=str(event.tenant_id),
            )
            return

        proposal_repo = TradeProposalRepository()
        proposal_row = await proposal_repo.get_by_id(event.proposal_id)
        if proposal_row is None:
            await self._bus.publish(
                ProposalRejected(
                    tenant_id=event.tenant_id,
                    proposal_id=event.proposal_id,
                    reason="proposal_missing",
                )
            )
            log.warning(
                "trading.execute.proposal_missing",
                proposal_id=str(event.proposal_id),
            )
            return

        # Whole-share guard (last line of defence before the broker): IBKR
        # rejects bracket/STP orders with fractional quantities. ``donchian_atr``
        # already floors at propose time, but coerce here too so a proposal from
        # any other strategy — or a legacy fractional row — never reaches
        # ``place_order``. Flooring is risk-conservative; if it floors below one
        # share the entry can't be sized, so reject cleanly (no Trade/Order to
        # orphan) instead of submitting a zero/fractional order.
        whole_quantity = Decimal(proposal_row.quantity).to_integral_value(rounding=ROUND_DOWN)
        if whole_quantity <= Decimal("0"):
            await self._bus.publish(
                ProposalRejected(
                    tenant_id=event.tenant_id,
                    proposal_id=event.proposal_id,
                    reason="below_min_size",
                )
            )
            log.warning(
                "trading.execute.below_min_size",
                proposal_id=str(event.proposal_id),
                requested_quantity=str(proposal_row.quantity),
            )
            return
        if whole_quantity != proposal_row.quantity:
            log.warning(
                "trading.execute.quantity_floored_to_whole_shares",
                proposal_id=str(event.proposal_id),
                requested_quantity=str(proposal_row.quantity),
                submitted_quantity=str(whole_quantity),
            )

        await proposal_repo.set_state(
            proposal_id=event.proposal_id,
            state="approved",
        )

        trade_repo = TradeRepository()
        trade_id = uuid4()
        opened_at = utc_now()
        trade = Trade(
            id=trade_id,
            tenant_id=event.tenant_id,
            proposal_id=event.proposal_id,
            symbol=proposal_row.symbol,
            side=proposal_row.side,
            quantity=whole_quantity,
            mode=proposal_row.mode,
            state="open",
            opened_at=opened_at,
        )
        await trade_repo.add(trade)
        # The Trade is the parent of the Order's ``trade_id`` FK. With no ORM
        # ``relationship`` between the two mappers, the unit-of-work does NOT
        # order the inserts by FK, so a combined flush emits the child Order
        # before its parent Trade and trips the constraint (rolling the whole
        # ledger write back). Flush the parent rows — the proposal state change
        # + the Trade — now so the later Order insert satisfies the FK.
        # (Unit-of-work boundary COMMITS are the #2/#27/#29 follow-up; this
        # only fixes the insert ORDERING within the flush.)
        await trade_repo.session.flush()

        # Audit #6 (minimal): thread the proposal's protective stop + target
        # into the order instead of discarding them. Audit #7: derive a
        # deterministic client_order_id from the proposal so a retry/reconcile
        # of this same logical entry dedupes broker-side.
        new_order = NewOrder(
            tenant_id=event.tenant_id,
            trade_id=trade_id,
            symbol=proposal_row.symbol,
            side=proposal_row.side,
            quantity=whole_quantity,
            order_type="market",
            stop_price=proposal_row.stop_price,
            target_price=proposal_row.target_price,
            client_order_id=derive_client_order_id(event.tenant_id, "entry", event.proposal_id),
            algo_kind=self._execution_algo,
        )

        order_id = uuid4()
        broker_order_id: BrokerOrderId | None = None
        rejection_reason: str | None = None
        try:
            broker_order_id = await asyncio.wait_for(
                self._broker.place_order(new_order),
                timeout=self._order_timeout_secs,
            )
        except TimeoutError:
            rejection_reason = "timeout"
            log.warning(
                "trading.execute.broker_timeout",
                proposal_id=str(event.proposal_id),
                timeout_secs=self._order_timeout_secs,
            )
        except BrokerAuthError as exc:
            rejection_reason = "broker_auth"
            log.warning(
                "trading.execute.broker_auth_error",
                proposal_id=str(event.proposal_id),
                error=str(exc),
            )
        except BudgetExceededError as exc:
            rejection_reason = "budget"
            log.warning(
                "trading.execute.budget_exceeded",
                proposal_id=str(event.proposal_id),
                error=str(exc),
            )
        except IntegrationError as exc:
            # Slice #8: any other broker/adapter failure — client not
            # connected, UnsupportedOrderTypeError, a broker NACK wrapped
            # as IntegrationError. Previously these propagated UNCAUGHT
            # out of the handler and (pre-WS0) killed the approval worker.
            # Record a rejected Order + OrderRejected so the proposal
            # reaches a terminal state and the open Trade is reconcilable.
            # (Kept BELOW BrokerAuthError, which subclasses IntegrationError.)
            rejection_reason = "broker_other"
            log.warning(
                "trading.execute.broker_error",
                proposal_id=str(event.proposal_id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
        except Exception as exc:
            # Last-resort guard: an unexpected error still yields a
            # persisted rejection rather than an orphaned open Trade.
            rejection_reason = "broker_other"
            log.error(
                "trading.execute.unexpected_error",
                proposal_id=str(event.proposal_id),
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )

        if rejection_reason == "timeout":
            # Audit #7: a submission that TIMED OUT may still be live at the
            # broker — marking it terminally 'rejected' would orphan a real
            # position while the DB claimed it never happened. Persist a
            # NON-terminal, reconcilable order keyed by the deterministic
            # client_order_id; the Trade stays 'open' and fill reconciliation
            # (or a manual sweep, once the adapter echoes order_ref) resolves
            # it. No OrderRejected is published — the order is not rejected.
            timeout_order = Order(
                id=order_id,
                tenant_id=event.tenant_id,
                trade_id=trade_id,
                broker="ibkr",
                broker_order_id=None,
                client_order_id=new_order.client_order_id,
                order_type=new_order.order_type,
                side=new_order.side,
                quantity=new_order.quantity,
                limit_price=None,
                stop_price=new_order.stop_price,
                target_price=new_order.target_price,
                state="timeout_pending",
            )
            await order_repo.add(timeout_order)
            log.warning(
                "trading.execute.timeout_pending_reconcile",
                order_id=str(order_id),
                client_order_id=str(new_order.client_order_id),
                proposal_id=str(event.proposal_id),
                tenant_id=str(event.tenant_id),
            )
            return

        if rejection_reason is not None:
            rejected_order = Order(
                id=order_id,
                tenant_id=event.tenant_id,
                trade_id=trade_id,
                broker="ibkr",
                broker_order_id=None,
                client_order_id=new_order.client_order_id,
                order_type=new_order.order_type,
                side=new_order.side,
                quantity=new_order.quantity,
                limit_price=None,
                stop_price=new_order.stop_price,
                target_price=new_order.target_price,
                state="rejected",
            )
            await order_repo.add(rejected_order)
            await self._bus.publish(
                OrderRejected(
                    tenant_id=event.tenant_id,
                    proposal_id=event.proposal_id,
                    reason=rejection_reason,
                )
            )
            return

        order = Order(
            id=order_id,
            tenant_id=event.tenant_id,
            trade_id=trade_id,
            broker="ibkr",
            broker_order_id=broker_order_id,
            client_order_id=new_order.client_order_id,
            order_type=new_order.order_type,
            side=new_order.side,
            quantity=new_order.quantity,
            limit_price=None,
            stop_price=new_order.stop_price,
            target_price=new_order.target_price,
            state="submitted",
            submitted_at=utc_now(),
        )
        await order_repo.add(order)
        await self._bus.publish(
            OrderPlaced(
                tenant_id=event.tenant_id,
                order_id=order_id,
                broker_order_id=broker_order_id,
            )
        )
        log.info(
            "trading.order.placed",
            order_id=str(order_id),
            broker_order_id=broker_order_id,
            proposal_id=str(event.proposal_id),
            tenant_id=str(event.tenant_id),
        )

    # ------------------------------------------------------------------
    # Restart reconciliation (slice order-timeout-restart-reconcile)
    # ------------------------------------------------------------------
    async def startup_reconcile(
        self,
        *,
        safety_margin_minutes: int = 10,
    ) -> None:
        """Drain any broker fills the daemon missed while it was down.

        Called once from the composition root (CLI startup) before
        :meth:`register_subscriptions`. Computes a ``since`` timestamp
        as ``max(filled_at) - safety_margin_minutes`` across all fills
        in the DB; falls back to ``now - 24 h`` if the DB is empty.

        The safety margin compensates for clock skew + the
        worst-case window where the broker recorded a fill but the
        daemon crashed before persisting it. The reconcile is
        idempotent at the broker_fill_id level (
        :meth:`_reconcile_one_fill` deduplicates), so a slightly-too-
        old ``since`` is preferable to a slightly-too-new one.
        """
        fill_repo = FillRepository()
        latest = await fill_repo.latest_filled_at()
        if latest is None:
            since = utc_now() - timedelta(hours=24)
            log.info(
                "trading.startup_reconcile.fallback_window",
                since=since.isoformat(),
                reason="no fills in DB yet",
            )
        else:
            since = latest - timedelta(minutes=safety_margin_minutes)
            log.info(
                "trading.startup_reconcile.computed_window",
                latest_fill_at=latest.isoformat(),
                since=since.isoformat(),
                safety_margin_minutes=safety_margin_minutes,
            )
        await self.reconcile_fills_handler(since)

    # ------------------------------------------------------------------
    # Step 6 — reconcile_fills_handler (skeleton; T4 fills logic)
    # ------------------------------------------------------------------
    async def reconcile_fills_handler(self, since: datetime) -> None:
        """On heartbeat tick / reconnect, drain ``BrokerPort.reconcile_fills(since)``.

        Slice T4 §2.C body fill: persist each :class:`Fill`, update
        :class:`Trade.state` when the order is fully filled, publish
        :class:`OrderFilled`, and snapshot equity on terminal state.
        """
        log.info("trading.fills.reconcile.started", since=since.isoformat())
        fill_repo = FillRepository()
        order_repo = OrderRepository()
        trade_repo = TradeRepository()
        equity_repo = EquitySnapshotRepository()

        async for fill_event in self._broker.reconcile_fills(since):
            # Bind the fill's tenant so the append-only / tenant guard accepts
            # the fills/equity inserts. The reconcile runs at boot + on the
            # heartbeat, outside any request/bus tenant scope, so tenant_id_var
            # would otherwise be unset and the insert raises
            # TenantContextMismatchError (audit #33). Per-fill scope keeps each
            # write bound to its own tenant.
            async with with_tenant_context(fill_event.tenant_id):
                await self._reconcile_one_fill(
                    fill_event,
                    fill_repo=fill_repo,
                    order_repo=order_repo,
                    trade_repo=trade_repo,
                    equity_repo=equity_repo,
                )
                # Audit #2: commit each reconciled fill at its unit-of-work
                # boundary. The boot/heartbeat reconcile runs on a long-lived
                # session that is otherwise never committed, so without this the
                # fill (and any terminal close/equity write) is logged as
                # persisted but rolled back when the session closes — the
                # position never lands in the ledger.
                session = session_var.get(None)
                if session is not None:
                    await session.commit()
        log.info("trading.fills.reconcile.completed")

    async def _reconcile_one_fill(
        self,
        fill_event: FillEvent,
        *,
        fill_repo: FillRepository,
        order_repo: OrderRepository,
        trade_repo: TradeRepository,
        equity_repo: EquitySnapshotRepository,
    ) -> None:
        """Process a single :class:`FillEvent` (slice T4 §2.C body)."""
        if fill_event.broker_fill_id and await fill_repo.exists_by_broker_fill_id(
            fill_event.broker_fill_id
        ):
            log.info(
                "trading.fill.dedup_skip",
                broker_fill_id=fill_event.broker_fill_id,
            )
            return

        # The broker echoes our ``order_ref`` (the deterministic
        # ``client_order_id``) on every fill, so resolve by that first — this
        # is what real IBKR executions carry. Fall back to the primary key for
        # call paths that reference an order by its id directly. Without the
        # client_order_id lookup, ``get_by_id`` is handed a client_order_id and
        # never matches, so genuine fills log ``order_missing`` and the position
        # is never recorded (the trade is left dangling open).
        order = await order_repo.get_by_client_order_id(
            fill_event.order_id
        ) or await order_repo.get_by_id(fill_event.order_id)
        if order is None:
            log.warning(
                "trading.fill.order_missing",
                order_id=str(fill_event.order_id),
                broker_fill_id=fill_event.broker_fill_id,
            )
            return

        fill_id = uuid4()
        fill = Fill(
            id=fill_id,
            tenant_id=fill_event.tenant_id,
            order_id=order.id,
            quantity_filled=fill_event.quantity_filled,
            fill_price=fill_event.fill_price,
            commission=fill_event.commission,
            commission_currency=fill_event.commission_currency,
            filled_at=fill_event.filled_at,
            broker_fill_id=fill_event.broker_fill_id,
        )
        await fill_repo.add(fill)

        total_filled = await fill_repo.sum_quantity_for_order(order.id)
        # `total_filled` already includes the just-added fill via the SUM.
        is_terminal = bool(Decimal(str(total_filled)) >= Decimal(str(order.quantity)))

        # Slice ``trade-close-flow-exit-pathway``: differentiate entry
        # vs exit fills by comparing the order's side to the trade's
        # side. An entry order has the same side as the trade (BUY for
        # a long); an exit order has the opposite (SELL for a long).
        # * Entry fill (terminal or partial): trade stays in
        #   ``state="open"`` (position is/becomes live; no state change).
        # * Exit fill terminal: transition trade to ``state="closed"``,
        #   stamp ``closed_at``, compute ``realised_pnl`` over all
        #   entry/exit fills.
        # * Exit fill partial: trade stays in ``state="closing"`` —
        #   ``close_trade`` already set that when the exit order was
        #   submitted; no state change here.
        trade = await trade_repo.get_by_id(order.trade_id)
        is_exit_fill = trade is not None and order.side != trade.side
        if is_exit_fill and is_terminal and trade is not None:
            realised_pnl = await self._compute_realised_pnl(
                trade=trade,
                fill_repo=fill_repo,
                order_repo=order_repo,
            )
            closed_at = utc_now()
            await trade_repo.update_state(
                trade.id,
                state="closed",
                closed_at=closed_at,
                realised_pnl=realised_pnl,
            )

            # Slice A3 — publish TradeClosed for the auto-journal
            # subscriber (and any future analytics consumers). Fire-and-
            # forget: a handler failure (LLM timeout, budget exceeded,
            # Hindsight retain network error) MUST NOT roll back this
            # close. Bus delivery itself is best-effort per the shared
            # messagebus contract.
            await self._bus.publish(
                TradeClosed(
                    tenant_id=trade.tenant_id,
                    trade_id=trade.id,
                    symbol=trade.symbol,
                    side=trade.side,
                    quantity=trade.quantity,
                    realised_pnl=realised_pnl,
                    exit_reason=str(trade.exit_reason or "manual"),
                    closed_at=closed_at,
                )
            )

        await self._bus.publish(
            OrderFilled(
                tenant_id=fill_event.tenant_id,
                order_id=order.id,
                fill_id=fill_id,
            )
        )
        log.info(
            "trading.fill.persisted",
            fill_id=str(fill_id),
            order_id=str(order.id),
            quantity_filled=str(fill_event.quantity_filled),
            fully_filled=is_terminal,
            is_exit_fill=is_exit_fill,
        )

        if is_terminal:
            equity_value = await self._broker.get_account_equity()
            snapshot_id = uuid4()
            snapshot = EquitySnapshot(
                id=snapshot_id,
                tenant_id=equity_value.tenant_id,
                mode=equity_value.mode,
                account_equity=equity_value.account_equity,
                cash_balance=equity_value.cash_balance,
                realized_pnl_today=equity_value.realized_pnl_today,
                unrealized_pnl=equity_value.unrealized_pnl,
                currency=equity_value.currency,
                snapshot_kind=equity_value.snapshot_kind,
            )
            await equity_repo.add(snapshot)
            await self._bus.publish(
                EquityUpdated(
                    tenant_id=equity_value.tenant_id,
                    equity_snapshot_id=snapshot_id,
                )
            )
            log.info(
                "trading.equity.snapshot_recorded",
                snapshot_id=str(snapshot_id),
                trade_id=str(order.trade_id),
                account_equity=str(equity_value.account_equity),
            )

    # ------------------------------------------------------------------
    # Cross-context — proposal rejected + halt
    # ------------------------------------------------------------------
    async def proposal_rejected_handler(self, event: ProposalRejected) -> None:
        """Subscriber: persist state + log the rejection.

        Slice ``dual-daemon-mode-toggle-and-reconcile``: propagate the
        rejection to ``trade_proposals.state`` so ``pending_proposals_count``
        + the drain logic can read the lifecycle from the row itself.
        Maps the canonical ``approval_timeout`` sentinel (timeout
        collapse) to ``state='expired'``; everything else (human
        rejection, daemon-drained, broker errors, etc.) lands as
        ``state='rejected'``.
        """
        proposal_repo = TradeProposalRepository()
        target_state = "expired" if event.reason == "approval_timeout" else "rejected"
        await proposal_repo.set_state(
            proposal_id=event.proposal_id,
            state=target_state,
            rejection_reason=event.reason,
        )
        log.info(
            "trading.proposal.rejected.received",
            proposal_id=str(event.proposal_id),
            reason=event.reason,
            tenant_id=str(event.tenant_id),
            target_state=target_state,
        )

    async def _is_halted(self, tenant_id: UUID) -> bool:
        """Return True iff the authoritative DB kill-switch is active.

        Defaults to the in-memory flag's value when no reader is wired
        (legacy/test path). Reader failures fail SAFE (treated as halted)
        for live execution — a risk read that cannot confirm the switch
        is off must not green-light a real order.
        """
        if self._kill_switch_reader is None:
            return self._kill_switch_active
        try:
            return await self._kill_switch_reader(tenant_id)
        except Exception:
            log.warning(
                "trading.kill_switch.read_failed_fail_safe",
                tenant_id=str(tenant_id),
                exc_info=True,
            )
            return True

    async def halt_handler(self, event: Any) -> None:
        """Subscriber: flip the internal halt flag.

        Wired to ``KillSwitchTripped`` once K1 lands; T1 declares the
        method against :class:`Any` because the K1 event class doesn't
        exist yet. K1's tasks will rebind the subscription to the real
        event type.
        """
        self._kill_switch_active = True
        reason = getattr(event, "reason", None) or "unspecified"
        log.warning(
            "trading.service.halted",
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Step 7 — close_trade (slice trade-close-flow-exit-pathway)
    # ------------------------------------------------------------------
    async def close_trade_handler(self, event: CloseTradeRequested) -> None:
        """Subscriber for :class:`CloseTradeRequested` (slice
        ``trade-close-flow-exit-pathway``).

        Wraps :meth:`close_trade` with structured logging + swallowed
        :class:`TradeNotClosableError` so a duplicate request against
        an already-closing trade does not blow up the bus consumer
        (the bus uses ``idempotent=True`` to dedupe on
        ``CloseTradeRequested.idempotency_key`` = trade_id, but the
        guard inside :meth:`close_trade` is the authoritative check).
        """
        try:
            await self.close_trade(event.trade_id, reason=event.reason)
        except TradeNotClosableError as exc:
            log.info(
                "trading.trade.close_not_closable",
                trade_id=str(event.trade_id),
                reason=event.reason,
                detail=exc.detail,
            )
        except Exception as exc:
            # Slice #25: defensive per-handler swallow. The MessageBus
            # worker now also guards handler exceptions (WS0), but a bad
            # CloseTradeRequested (e.g. an invalid reason raising
            # ValueError, or a transient broker error) must not abort the
            # close subscriber; log and continue so subsequent valid
            # close requests still process.
            log.error(
                "trading.trade.close_failed",
                trade_id=str(event.trade_id),
                reason=event.reason,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )

    async def close_trade(self, trade_id: UUID, *, reason: str) -> BrokerOrderId:
        """Submit an exit order for ``trade_id``; transition state to "closing".

        Idempotency: only trades in ``state="open"`` are closable. A
        trade already in ``state="closing"`` (an exit order is
        pending) or ``state="closed"`` (terminal) raises
        :class:`TradeNotClosableError` (HTTP 409).

        ``reason`` must be one of the four canonical exit categories
        (``stop`` / ``target`` / ``manual`` / ``expiry``) — mirrors
        the ``ck_trades_exit_reason_allowed`` DB constraint added in
        slice 0015. Stored on the Trade row at close-submit time so
        the terminal fill reconciliation does not need to know the
        original trigger.

        The exit order has the opposite side (``buy`` → ``sell`` for a
        long), the trade's full quantity (partial exits are v2), and
        the tenant's configured execution algo (slice
        ``ibkr-execution-algos-entry``). Returns the broker's order id
        so callers (manual API endpoint, trailing-stops sweep) can
        correlate.
        """
        if reason not in _VALID_EXIT_REASONS:
            raise ValueError(f"reason must be one of {sorted(_VALID_EXIT_REASONS)}, got {reason!r}")

        trade_repo = TradeRepository()
        order_repo = OrderRepository()
        trade = await trade_repo.get_by_id(trade_id)
        if trade is None:
            raise TradeNotClosableError(detail=f"trade {trade_id} not found")
        if trade.state != "open":
            raise TradeNotClosableError(
                detail=(
                    f"trade {trade_id} is in state={trade.state!r}; "
                    "only 'open' trades can be closed"
                )
            )

        opposite_side = "sell" if trade.side == "buy" else "buy"
        # Audit #7: deterministic client_order_id for the exit leg, keyed by
        # the trade (distinct 'exit' role so it never collides with the entry
        # order's key on the per-tenant UNIQUE constraint). A retried close
        # after a transient broker hang dedupes broker-side.
        new_order = NewOrder(
            tenant_id=trade.tenant_id,
            trade_id=trade_id,
            symbol=trade.symbol,
            side=opposite_side,
            quantity=trade.quantity,
            order_type="market",
            client_order_id=derive_client_order_id(trade.tenant_id, "exit", trade_id),
            algo_kind=self._execution_algo,
        )
        # Slice ``order-timeout-restart-reconcile``: bail on a hung
        # broker socket. ``close_trade`` is invoked from the manual
        # close API + the trailing-stops sweep + take-profit handlers;
        # any of these would back-pressure the message bus if the
        # broker hangs. Surface as a ``TimeoutError`` for the caller
        # rather than masking — the API handler already maps the
        # exception to RFC 7807 status 504 via the global error chain.
        broker_order_id = await asyncio.wait_for(
            self._broker.place_order(new_order),
            timeout=self._order_timeout_secs,
        )

        exit_order_id = uuid4()
        exit_order = Order(
            id=exit_order_id,
            tenant_id=trade.tenant_id,
            trade_id=trade_id,
            broker="ibkr",
            broker_order_id=broker_order_id,
            client_order_id=new_order.client_order_id,
            order_type=new_order.order_type,
            side=opposite_side,
            quantity=trade.quantity,
            limit_price=None,
            stop_price=None,
            state="submitted",
            submitted_at=utc_now(),
        )
        await order_repo.add(exit_order)
        await trade_repo.update_state(trade_id, state="closing", exit_reason=reason)

        await self._bus.publish(
            OrderPlaced(
                tenant_id=trade.tenant_id,
                order_id=exit_order_id,
                broker_order_id=broker_order_id,
            )
        )
        log.info(
            "trading.trade.close_submitted",
            trade_id=str(trade_id),
            exit_order_id=str(exit_order_id),
            broker_order_id=broker_order_id,
            reason=reason,
            tenant_id=str(trade.tenant_id),
        )
        return broker_order_id

    async def _compute_realised_pnl(
        self,
        *,
        trade: Trade,
        fill_repo: FillRepository,
        order_repo: OrderRepository,
    ) -> Decimal:
        """Compute realised P&L over the trade's full entry + exit fills.

        For a long (``trade.side == "buy"``):
        ``realised_pnl = exit_proceeds - entry_cost - commissions``
        where:
        * ``entry_cost = sum(fill.quantity * fill.price)`` over fills
          whose order shares the trade's side.
        * ``exit_proceeds = sum(fill.quantity * fill.price)`` over
          fills whose order has the opposite side.
        * ``commissions`` = total commission across all fills (both
          legs) — broker debits commission on each fill regardless of
          leg.

        For a short, the formula inverts: ``entry_proceeds -
        exit_cost - commissions`` (sold high to enter, bought low to
        exit).

        Returns ``Decimal("0")`` if the trade has no exit fills yet
        (shouldn't fire in production — the caller gates on
        ``is_exit_fill and is_terminal``).
        """
        all_orders = await order_repo.list_for_trade(trade.id)
        side_by_order: dict[UUID, str] = {o.id: o.side for o in all_orders}
        fills = await fill_repo.list_for_trade(trade.id)

        entry_value = Decimal("0")
        exit_value = Decimal("0")
        total_commission = Decimal("0")
        for fill in fills:
            order_side = side_by_order.get(fill.order_id)
            if order_side is None:
                # Defensive: orphan fill (shouldn't happen given FK).
                continue
            qty = Decimal(str(fill.quantity_filled))
            price = Decimal(str(fill.fill_price))
            commission = Decimal(str(fill.commission or 0))
            value = qty * price
            total_commission += commission
            if order_side == trade.side:
                entry_value += value
            else:
                exit_value += value

        if trade.side == "buy":
            return exit_value - entry_value - total_commission
        return entry_value - exit_value - total_commission


__all__ = [
    "KillSwitchActiveError",
    "StrategyResolver",
    "TradeNotClosableError",
    "TradingService",
]
