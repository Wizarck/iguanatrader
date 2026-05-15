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

from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog

from iguanatrader.contexts.observability.errors import BudgetExceededError
from iguanatrader.contexts.trading.brokers.ibkr_adapter import BrokerAuthError
from iguanatrader.contexts.trading.events import (
    ApprovalRequested,
    EquityUpdated,
    OrderFilled,
    OrderPlaced,
    OrderRejected,
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    ProposalRiskEvaluated,
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
)
from iguanatrader.contexts.trading.repository import (
    EquitySnapshotRepository,
    FillRepository,
    OrderRepository,
    TradeProposalRepository,
    TradeRepository,
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
# Slice T4-followup-market-data: signature changed to async so production
# closures can do session-scoped DB lookups (StrategyConfigRepository.get_by_id).
# Tests that previously injected ``lambda id: mapping[id]`` need a 1-line
# wrapper: ``async def _resolve(id): return mapping[id]``.
StrategyResolver = Callable[[UUID], Awaitable[StrategyPort]]


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
    ) -> None:
        self._bus = bus
        self._broker = broker
        self._strategy_resolver = strategy_resolver
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

        trade_repo = TradeRepository()
        trade_id = uuid4()
        opened_at = utc_now()
        trade = Trade(
            id=trade_id,
            tenant_id=event.tenant_id,
            proposal_id=event.proposal_id,
            symbol=proposal_row.symbol,
            side=proposal_row.side,
            quantity=proposal_row.quantity,
            mode=proposal_row.mode,
            state="open",
            opened_at=opened_at,
        )
        await trade_repo.add(trade)

        new_order = NewOrder(
            tenant_id=event.tenant_id,
            trade_id=trade_id,
            symbol=proposal_row.symbol,
            side=proposal_row.side,
            quantity=proposal_row.quantity,
            order_type="market",
            client_order_id=uuid4(),
            algo_kind=self._execution_algo,
        )

        order_id = uuid4()
        broker_order_id: BrokerOrderId | None = None
        rejection_reason: str | None = None
        try:
            broker_order_id = await self._broker.place_order(new_order)
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

        if rejection_reason is not None:
            rejected_order = Order(
                id=order_id,
                tenant_id=event.tenant_id,
                trade_id=trade_id,
                broker="ibkr",
                broker_order_id=None,
                order_type=new_order.order_type,
                side=new_order.side,
                quantity=new_order.quantity,
                limit_price=None,
                stop_price=None,
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
            order_type=new_order.order_type,
            side=new_order.side,
            quantity=new_order.quantity,
            limit_price=None,
            stop_price=None,
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
            await self._reconcile_one_fill(
                fill_event,
                fill_repo=fill_repo,
                order_repo=order_repo,
                trade_repo=trade_repo,
                equity_repo=equity_repo,
            )
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

        order = await order_repo.get_by_id(fill_event.order_id)
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
            order_id=fill_event.order_id,
            quantity_filled=fill_event.quantity_filled,
            fill_price=fill_event.fill_price,
            commission=fill_event.commission,
            broker_fill_id=fill_event.broker_fill_id,
        )
        await fill_repo.add(fill)

        total_filled = await fill_repo.sum_quantity_for_order(fill_event.order_id)
        # `total_filled` already includes the just-added fill via the SUM.
        is_terminal = bool(Decimal(str(total_filled)) >= Decimal(str(order.quantity)))
        if is_terminal:
            closed_at = utc_now()
            await trade_repo.update_state(order.trade_id, state="closed", closed_at=closed_at)
        else:
            await trade_repo.update_state(order.trade_id, state="partial")

        await self._bus.publish(
            OrderFilled(
                tenant_id=fill_event.tenant_id,
                order_id=fill_event.order_id,
                fill_id=fill_id,
            )
        )
        log.info(
            "trading.fill.persisted",
            fill_id=str(fill_id),
            order_id=str(fill_event.order_id),
            quantity_filled=str(fill_event.quantity_filled),
            fully_filled=is_terminal,
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
