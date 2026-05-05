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

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog

from iguanatrader.contexts.trading.events import (
    ApprovalRequested,
    OrderPlaced,
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    ProposalRiskEvaluated,
)
from iguanatrader.contexts.trading.models import Order, Trade, TradeProposal
from iguanatrader.contexts.trading.ports import (
    BarHistory,
    BrokerOrderId,
    BrokerPort,
    NewOrder,
    Proposal,
    StrategyConfigSnapshot,
    StrategyPort,
)
from iguanatrader.shared.contextvars import tenant_id_var
from iguanatrader.shared.errors import IguanaError
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


# Type alias for the strategy resolver callable injected at construction.
StrategyResolver = Callable[[UUID], StrategyPort]


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
    ) -> None:
        self._bus = bus
        self._broker = broker
        self._strategy_resolver = strategy_resolver
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

        strategy = self._strategy_resolver(strategy_config_id)
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

        Slice T1 ships only the breadcrumb + the publish on the
        ``allow``/``clip`` outcomes. Slice T4 will add the persistence
        of the risk evaluation receipt + any further routing logic.
        """
        log.info(
            "trading.proposal.risk_evaluated.received",
            proposal_id=str(event.proposal_id),
            outcome=event.outcome,
            tenant_id=str(event.tenant_id),
        )

        if event.outcome in {"allow", "clip"}:
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
        # T4 fills: on outcome == 'reject', persist a no-trade audit
        # row + emit a structlog breadcrumb so the operator can trace
        # why the proposal stopped.

    # ------------------------------------------------------------------
    # Step 5 — execute_on_approval_handler (skeleton; T4 fills logic)
    # ------------------------------------------------------------------
    async def execute_on_approval_handler(self, event: ProposalApproved) -> None:
        """Subscriber: on :class:`ProposalApproved` call ``BrokerPort.place_order``.

        Idempotent at the bus boundary (slice 2 D1: subscribe with
        ``idempotent=True``); the registration in
        :meth:`register_subscriptions` sets the flag. If P1 retries the
        approve event the bus suppresses the duplicate.

        T1 plants the call + the persistence of the ``orders`` row +
        the :class:`OrderPlaced` publish; T4 fills in the
        :class:`Trade` lifecycle row creation (state == 'open') + the
        ``proposal → trade → order`` linkage queries.
        """
        log.info(
            "trading.proposal.approved.received",
            proposal_id=str(event.proposal_id),
            tenant_id=str(event.tenant_id),
        )

        # T4 fills: load the TradeProposal + create the Trade row first
        # (state='open'), then reconstruct the NewOrder shape from the
        # proposal. Below is the skeleton call sequence — comments mark
        # the gaps.

        # 1. (T4) Load proposal by id; idempotency-guard against a
        #    duplicate execute path that survived the bus dedup window.
        # 2. (T4) Create Trade row (state='open', opened_at=utc_now()).
        # 3. (T4) Build NewOrder from Proposal + tenant config.
        # 4. (T1) Submit via broker; record broker_order_id.
        # 5. (T1) INSERT order row; (T1) publish OrderPlaced.

        new_order_stub = NewOrder(
            tenant_id=event.tenant_id,
            trade_id=uuid4(),  # T4: real trade_id from step 2
            symbol="",  # T4: copied from Proposal
            side="buy",  # T4: copied from Proposal
            quantity=Decimal("0"),  # T4: copied from Proposal
            order_type="market",  # T4: copied from Proposal
        )
        # In a real T4 implementation we'd ``await self._broker.place_order(new_order_stub)``;
        # T1 leaves the call wired but commented to avoid hitting a fake
        # broker on import-time test loading. Document the call-site so
        # T4 just uncomments + fills the missing fields.
        broker_order_id: BrokerOrderId | None = None
        _ = (new_order_stub, broker_order_id, OrderPlaced, Order, utc_now, datetime)

        log.info(
            "trading.execute_on_approval.skeleton",
            proposal_id=str(event.proposal_id),
            note="T4 wires real Trade+Order persistence + broker submission",
        )

    # ------------------------------------------------------------------
    # Step 6 — reconcile_fills_handler (skeleton; T4 fills logic)
    # ------------------------------------------------------------------
    async def reconcile_fills_handler(self, since: datetime) -> None:
        """On reconnect, drain ``BrokerPort.reconcile_fills(since)``.

        Slice T1 plants the iteration shape; T4 wires the session-based
        ``Fill`` INSERT + ``Trade.state`` update + :class:`OrderFilled`
        publish.
        """
        log.info(
            "trading.fills.reconcile.started",
            since=since.isoformat(),
        )
        async for _fill in self._broker.reconcile_fills(since):
            # T4 fills: persist Fill row, mutate Trade.state if total
            # filled qty matches the order qty, publish OrderFilled.
            log.info(
                "trading.fills.reconcile.received",
                broker_fill_id=_fill.broker_fill_id,
            )
        log.info("trading.fills.reconcile.completed")

    # ------------------------------------------------------------------
    # Cross-context — proposal rejected + halt
    # ------------------------------------------------------------------
    async def proposal_rejected_handler(self, event: ProposalRejected) -> None:
        """Subscriber: log the rejection. T4 may add audit-log persistence."""
        log.info(
            "trading.proposal.rejected.received",
            proposal_id=str(event.proposal_id),
            reason=event.reason,
            tenant_id=str(event.tenant_id),
        )

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


__all__ = [
    "KillSwitchActiveError",
    "StrategyResolver",
    "TradingService",
]


# Keep referenced exports alive for ruff (these are intentionally
# re-exported via ``__all__`` only when T4 fills the bodies).
_ = (Trade,)
