"""ApprovalService — orchestrate the approval lifecycle.

Per slice P1 design D7: the service is the only path that writes
``approval_decisions`` rows AND emits the corresponding cross-context
events on the slice-2 :class:`MessageBus`. Channels + the dashboard
route never publish events directly — they call the service.

Lifecycle:

    create_request → fan_out_to_channels → record_decision → emit_event

Plus the periodic timeout sweeper:

    sweep_expired_requests → record_decision(outcome='timeout') → emit_event

Structlog naming convention (slice 2 + slice P1):

* ``approval.request.created`` — INSERT of approval_requests row.
* ``approval.decision.recorded`` — INSERT of approval_decisions row.
* ``approval.proposal.{approved,rejected,timed_out}`` — mirrored on
  the bus event names so log/event correlation is grep-able.
* ``approval.channel.<channel>.delivery_failed`` — fan-out failure on
  one channel (FR32 isolation).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import structlog

from iguanatrader.contexts.approval.channels.types import (
    ApprovalDecisionRow,
    ApprovalRequestRow,
    ChannelKind,
)
from iguanatrader.contexts.approval.errors import (
    ApprovalExpiredError,
    ApprovalNotFoundError,
)
from iguanatrader.contexts.approval.events import (
    ApprovalProposalApproved,
    ApprovalProposalRejected,
    ApprovalProposalTimedOut,
)
from iguanatrader.contexts.approval.repository import ApprovalRepository
from iguanatrader.shared.messagebus import MessageBus
from iguanatrader.shared.time import now as utc_now

log = structlog.get_logger("iguanatrader.contexts.approval.service")


_DEFAULT_APPROVAL_CHANNELS = "telegram,dashboard"
_DEFAULT_APPROVAL_TIMEOUT_SECONDS = 300
_TIMEOUT_MIN_SECONDS = 1
_TIMEOUT_MAX_SECONDS = 86400


def _as_aware_utc(value: datetime) -> datetime:
    """Coerce ``value`` to a tz-aware UTC datetime.

    #30: ``DateTime(timezone=True)`` columns round-trip tz-aware on
    Postgres but **naive** on SQLite/aiosqlite. Comparing a naive
    ``expires_at`` against the tz-aware :func:`utc_now` raises
    ``TypeError`` — and the pre-existing latency subtraction had the same
    latent fragility (no SQLite round-trip test exercised the granted
    path). Treat a naive value as already-UTC.
    """
    from iguanatrader.shared.time import UTC

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _parse_approval_channels(raw: str | None) -> list[str]:
    """Parse ``IGUANATRADER_DEFAULT_APPROVAL_CHANNELS`` (comma-separated).

    Default ``"telegram,dashboard"`` per slice P1-followup §2.7 (env-var
    first-cut; v2 SaaS swaps to a per-tenant ``approval_defaults`` table).
    """
    csv = (raw or _DEFAULT_APPROVAL_CHANNELS).strip()
    return [chan.strip().lower() for chan in csv.split(",") if chan.strip()]


def _parse_approval_timeout(raw: str | None) -> int:
    """Parse ``IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS`` + clamp.

    Clamped to ``[1, 86400]`` (1s … 24h). Falls back to 300s on parse
    failure or empty.
    """
    if raw is None or not raw.strip():
        return _DEFAULT_APPROVAL_TIMEOUT_SECONDS
    try:
        value = int(raw.strip())
    except ValueError:
        return _DEFAULT_APPROVAL_TIMEOUT_SECONDS
    return max(_TIMEOUT_MIN_SECONDS, min(_TIMEOUT_MAX_SECONDS, value))


class ApprovalService:
    """Coordinator for approval lifecycle + event emission."""

    def __init__(
        self,
        *,
        repository: ApprovalRepository,
        message_bus: MessageBus,
        channel_dispatcher: Any | None = None,
    ) -> None:
        self._repository = repository
        self._message_bus = message_bus
        # Slice p1-followup-channel-fanout: optional ChannelDispatcher
        # for bus-driven channel push. None = no fanout (existing P1
        # archive behaviour). Set by the daemon via
        # `build_channel_dispatcher_from_env()`.
        self._channel_dispatcher = channel_dispatcher

    async def create_request(
        self,
        *,
        proposal_id: UUID | None = None,
        channels: Sequence[str],
        timeout_seconds: int,
        action_type: str = "entry",
        trade_id: UUID | None = None,
    ) -> ApprovalRequestRow:
        """Persist a new approval request + log creation.

        Fan-out to channels is the channels' responsibility (the
        service hands the row to each channel adapter via the route /
        dispatcher). This method is the audit-write entry point only.

        WS-5 PR-B: ``action_type='exit'`` rows carry ``trade_id`` (and a NULL
        ``proposal_id``) so the granted bridge closes that trade instead of
        opening a position.
        """
        row = await self._repository.create_request(
            proposal_id=proposal_id,
            delivered_to_channels=list(channels),
            timeout_seconds=timeout_seconds,
            action_type=action_type,
            trade_id=trade_id,
        )
        log.info(
            "approval.request.created",
            request_id=str(row.id),
            proposal_id=str(proposal_id) if proposal_id is not None else None,
            action_type=action_type,
            trade_id=str(trade_id) if trade_id is not None else None,
            channels=list(channels),
            timeout_seconds=timeout_seconds,
            expires_at=row.expires_at.isoformat(),
        )
        return row

    async def record_decision(
        self,
        *,
        request_id: UUID,
        outcome: Literal["granted", "rejected", "timeout"],
        decided_via_channel: ChannelKind,
        decided_by_user_id: UUID | None = None,
        decided_by_sender_id: UUID | None = None,
        reason: str | None = None,
    ) -> ApprovalDecisionRow:
        """Append an :class:`ApprovalDecision` row + emit the event.

        Latency is computed from the matching request's ``created_at``
        — clamped at 0 so a clock-skew negative never breaks the CHECK
        constraint. Raises :class:`ApprovalNotFoundError` if the
        request does not exist (404).
        """
        request = await self._repository.get_request(request_id)
        if request is None:
            raise ApprovalNotFoundError(
                detail=f"No approval request found for id={request_id}.",
            )
        decided_at = utc_now()
        # #30: a human decision (granted/rejected) that lands at or after
        # ``expires_at`` races the timeout sweeper — both would persist a
        # decision and the bus would emit BOTH the approve/reject event AND
        # ``approval_timeout`` for the same proposal (double execution / split
        # state). Reject the late decision deterministically with 410. The
        # sweeper's own timeout path calls the repository directly (not this
        # method), so it is exempt; ``outcome == "timeout"`` is likewise
        # never gated here.
        if outcome in ("granted", "rejected") and decided_at >= _as_aware_utc(request.expires_at):
            raise ApprovalExpiredError(
                detail=(
                    f"Approval request {request_id} expired at "
                    f"{request.expires_at.isoformat()}; a {outcome!r} decision at "
                    f"{decided_at.isoformat()} is too late to record."
                ),
            )
        latency_ms = int(
            max(
                (decided_at - _as_aware_utc(request.created_at)).total_seconds() * 1000,
                0.0,
            )
        )
        decision = await self._repository.record_decision(
            request_id=request_id,
            outcome=outcome,
            decided_via_channel=decided_via_channel,
            decided_by_user_id=decided_by_user_id,
            decided_by_sender_id=decided_by_sender_id,
            latency_ms=latency_ms,
        )
        log.info(
            "approval.decision.recorded",
            request_id=str(request_id),
            decision_id=str(decision.id),
            outcome=outcome,
            channel=decided_via_channel,
            latency_ms=latency_ms,
        )
        await self._publish_event(
            request=request,
            decision=decision,
            outcome=outcome,
            decided_at=decided_at,
            reason=reason,
        )
        return decision

    async def sweep_expired_requests(
        self,
        *,
        now: datetime | None = None,
    ) -> list[ApprovalDecisionRow]:
        """Find expired pending requests + record timeout decisions.

        Idempotent: requests that already have a decision row (e.g.
        decided in the same tick) are filtered out by
        :meth:`ApprovalRepository.sweep_expired`. Each timeout INSERT
        also emits exactly one ``approval.proposal.timed_out`` event.
        """
        when = now if now is not None else utc_now()
        expired = await self._repository.sweep_expired(when)
        decisions: list[ApprovalDecisionRow] = []
        for request in expired:
            latency_ms = int(
                max(
                    (request.expires_at - request.created_at).total_seconds() * 1000,
                    0.0,
                )
            )
            decision = await self._repository.record_decision(
                request_id=request.id,
                outcome="timeout",
                decided_via_channel="timeout",
                decided_by_user_id=None,
                decided_by_sender_id=None,
                latency_ms=latency_ms,
            )
            log.info(
                "approval.decision.recorded",
                request_id=str(request.id),
                decision_id=str(decision.id),
                outcome="timeout",
                channel="timeout",
                latency_ms=latency_ms,
            )
            await self._message_bus.publish(
                ApprovalProposalTimedOut(
                    proposal_id=request.proposal_id,
                    request_id=request.id,
                    expired_at=request.expires_at,
                    tenant_id=request.tenant_id,
                )
            )
            decisions.append(decision)
        return decisions

    async def _publish_event(
        self,
        *,
        request: ApprovalRequestRow,
        decision: ApprovalDecisionRow,
        outcome: Literal["granted", "rejected", "timeout"],
        decided_at: datetime,
        reason: str | None,
    ) -> None:
        """Translate outcome → bus event + publish exactly once."""
        # WS-5 PR-B: carry the request's action discriminator + trade_id onto
        # every outcome event so the outbound bridge stays action-aware.
        action_type = getattr(request, "action_type", "entry")
        trade_id = getattr(request, "trade_id", None)
        event: Any
        if outcome == "granted":
            event = ApprovalProposalApproved(
                proposal_id=request.proposal_id,
                decision_id=decision.id,
                decided_at=decided_at,
                decided_by_user_id=decision.decided_by_user_id,
                decided_via_channel=decision.decided_via_channel,
                tenant_id=request.tenant_id,
                action_type=action_type,
                trade_id=trade_id,
            )
        elif outcome == "rejected":
            event = ApprovalProposalRejected(
                proposal_id=request.proposal_id,
                decision_id=decision.id,
                decided_at=decided_at,
                reason=reason,
                decided_via_channel=decision.decided_via_channel,
                tenant_id=request.tenant_id,
                action_type=action_type,
                trade_id=trade_id,
            )
        else:
            event = ApprovalProposalTimedOut(
                proposal_id=request.proposal_id,
                request_id=request.id,
                expired_at=request.expires_at,
                tenant_id=request.tenant_id,
                action_type=action_type,
                trade_id=trade_id,
            )
        await self._message_bus.publish(event)

    # ------------------------------------------------------------------
    # Slice P1-followup-bus-subscriptions §2 — bus bridge.
    #
    # Inbound: trading.ApprovalRequested → create_request audit-write.
    # Outbound: ApprovalProposal{Approved,Rejected,TimedOut} translated
    # to trading-flavored events (T4 already subscribes to those).
    # ------------------------------------------------------------------

    def register_subscriptions(self, bus: MessageBus | None = None) -> None:
        """Wire bus subscriptions: 1 inbound + 3 outbound bridges.

        All four subscriptions use ``idempotent=True`` (slice 2 D1) so
        re-registration on daemon restart is safe. The daemon calls this
        once per service instance on startup; tests construct fresh
        services per test.
        """
        target_bus = bus if bus is not None else self._message_bus
        if target_bus is None:
            raise RuntimeError(
                "ApprovalService.register_subscriptions requires a "
                "MessageBus via constructor injection or method arg."
            )

        from iguanatrader.contexts.trading.events import (
            ApprovalRequested,
            ExitApprovalRequested,
        )

        target_bus.subscribe(
            ApprovalRequested,
            self._approval_requested_handler,
            idempotent=True,
        )
        # WS-5 PR-B: the urgent-exit advisor raises ExitApprovalRequested → the
        # same fan-out machinery, tagged action_type='exit'.
        target_bus.subscribe(
            ExitApprovalRequested,
            self._exit_approval_requested_handler,
            idempotent=True,
        )
        target_bus.subscribe(
            ApprovalProposalApproved,
            self._bridge_to_trading_approved_handler,
            idempotent=True,
        )
        target_bus.subscribe(
            ApprovalProposalRejected,
            self._bridge_to_trading_rejected_handler,
            idempotent=True,
        )
        target_bus.subscribe(
            ApprovalProposalTimedOut,
            self._bridge_to_trading_timeout_handler,
            idempotent=True,
        )

    async def _approval_requested_handler(self, event: Any) -> None:
        """Inbound bridge: persist the approval_request row.

        Channel push fan-out (Telegram bot send, Hermes HTTP) is
        deliberately deferred to ``P1-followup-channel-fanout``;
        dashboard SSE + ``POST /approvals/{id}/{approve,reject}`` routes
        already drive the human-decision path.
        """
        import os

        channels = _parse_approval_channels(
            os.environ.get("IGUANATRADER_DEFAULT_APPROVAL_CHANNELS")
        )
        timeout_seconds = _parse_approval_timeout(
            os.environ.get("IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS")
        )
        row = await self.create_request(
            proposal_id=event.proposal_id,
            channels=channels,
            timeout_seconds=timeout_seconds,
        )
        log.info(
            "approval.bus.request_persisted",
            proposal_id=str(event.proposal_id),
            request_id=str(row.id),
            channels=list(channels),
            timeout_seconds=timeout_seconds,
        )

        # Slice p1-followup-channel-fanout: dispatcher fan-out after
        # the audit-write. Failures are caught + swallowed (FR32:
        # one bad dispatcher must not bring down the audit-write
        # path; the bus chain still continues).
        if self._channel_dispatcher is not None:
            try:
                await self._channel_dispatcher.fanout(
                    request=row,
                    channels=channels,
                )
            except Exception as exc:
                log.warning(
                    "approval.bus.fanout_failed",
                    proposal_id=str(event.proposal_id),
                    request_id=str(row.id),
                    error=str(exc),
                )

    async def _exit_approval_requested_handler(self, event: Any) -> None:
        """Inbound bridge for WS-5: persist an EXIT approval request + fan out.

        Mirrors :meth:`_approval_requested_handler` but tags the row
        ``action_type='exit'`` with the ``trade_id`` to close and a NULL
        ``proposal_id``. On a granted decision the action-aware approved
        bridge publishes :class:`CloseTradeRequested`. NEVER closes here —
        this only raises the Telegram approve/deny card.
        """
        import os

        channels = _parse_approval_channels(
            os.environ.get("IGUANATRADER_DEFAULT_APPROVAL_CHANNELS")
        )
        timeout_seconds = _parse_approval_timeout(
            os.environ.get("IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS")
        )
        row = await self.create_request(
            proposal_id=None,
            channels=channels,
            timeout_seconds=timeout_seconds,
            action_type="exit",
            trade_id=event.trade_id,
        )
        log.info(
            "approval.bus.exit_request_persisted",
            trade_id=str(event.trade_id),
            request_id=str(row.id),
            symbol=getattr(event, "symbol", None),
            channels=list(channels),
            timeout_seconds=timeout_seconds,
        )

        if self._channel_dispatcher is not None:
            try:
                await self._channel_dispatcher.fanout(
                    request=row,
                    channels=channels,
                )
            except Exception as exc:
                log.warning(
                    "approval.bus.exit_fanout_failed",
                    trade_id=str(event.trade_id),
                    request_id=str(row.id),
                    error=str(exc),
                )

    async def _bridge_to_trading_approved_handler(self, event: ApprovalProposalApproved) -> None:
        """Outbound bridge: a granted decision → the action it authorises.

        FAIL-CLOSED on ``action_type`` (WS-5 PR-B). A granted approval means
        OPEN a position only when ``action_type == 'entry'`` (→
        ``trading.ProposalApproved`` → ``place_order``); it means CLOSE a
        position only when ``action_type == 'exit'`` (→
        ``CloseTradeRequested(reason='manual')``). ANY other value — unknown,
        empty, an exit row with no ``trade_id``, an entry row with no
        ``proposal_id`` — publishes NEITHER and logs an error. This guarantees
        a granted EXIT can never accidentally fire a BUY (and vice-versa).

        Tenant id is resolved from :data:`tenant_id_var` (slice 2 D2); if the
        ContextVar is unset (test outside request scope) we log and skip
        rather than emit a tenant-less event.
        """
        from iguanatrader.contexts.trading.events import (
            CloseTradeRequested,
            ProposalApproved,
        )
        from iguanatrader.shared.contextvars import tenant_id_var

        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            log.error(
                "approval.bus.bridge_skipped_no_tenant",
                bridge="approved",
                proposal_id=str(event.proposal_id),
            )
            return

        action_type = getattr(event, "action_type", "entry")

        if action_type == "exit":
            if event.trade_id is None:
                log.error(
                    "approval.bus.exit_bridge_missing_trade_id",
                    decision_id=str(event.decision_id),
                )
                return
            close = CloseTradeRequested(
                tenant_id=tenant_id,
                trade_id=event.trade_id,
                reason="manual",
                metadata={
                    "source": "urgent_exit_approval",
                    "decision_id": str(event.decision_id),
                    "decided_at": (
                        event.decided_at.isoformat() if event.decided_at is not None else None
                    ),
                    "decided_via_channel": event.decided_via_channel,
                },
            )
            await self._message_bus.publish(close)
            log.info(
                "approval.bus.translated_to_close_trade",
                trade_id=str(event.trade_id),
                decision_id=str(event.decision_id),
                decided_via_channel=event.decided_via_channel,
            )
            return

        if action_type != "entry":
            # FAIL-CLOSED: an unrecognised discriminator must never open a
            # position. Better to drop a granted approval (the operator can
            # re-issue) than to execute the wrong real-money action.
            log.error(
                "approval.bus.approved_bridge_unknown_action_type",
                action_type=str(action_type),
                decision_id=str(event.decision_id),
            )
            return

        if event.proposal_id is None:
            log.error(
                "approval.bus.approved_bridge_entry_missing_proposal",
                decision_id=str(event.decision_id),
            )
            return

        translated = ProposalApproved(
            tenant_id=tenant_id,
            proposal_id=event.proposal_id,
            approved_by_user_id=event.decided_by_user_id,
            metadata={
                "decision_id": str(event.decision_id),
                "decided_at": (
                    event.decided_at.isoformat() if event.decided_at is not None else None
                ),
                "decided_via_channel": event.decided_via_channel,
            },
        )
        await self._message_bus.publish(translated)
        log.info(
            "approval.bus.translated_to_trading_approved",
            proposal_id=str(event.proposal_id),
            decision_id=str(event.decision_id),
            decided_via_channel=event.decided_via_channel,
        )

    async def _bridge_to_trading_rejected_handler(self, event: ApprovalProposalRejected) -> None:
        """Outbound bridge: ApprovalProposalRejected → trading.ProposalRejected."""
        from iguanatrader.contexts.trading.events import ProposalRejected
        from iguanatrader.shared.contextvars import tenant_id_var

        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            log.error(
                "approval.bus.bridge_skipped_no_tenant",
                bridge="rejected",
                proposal_id=str(event.proposal_id),
            )
            return

        if getattr(event, "action_type", "entry") == "exit":
            # An EXIT approval the operator declined: keep the position open,
            # do NOT emit ProposalRejected (there is no proposal to archive).
            # The advisor re-raises on a later tick if the urgent condition
            # persists.
            log.info(
                "approval.bus.exit_kept_open",
                trade_id=str(event.trade_id),
                decision_id=str(event.decision_id),
                reason=event.reason,
            )
            return

        translated = ProposalRejected(
            tenant_id=tenant_id,
            proposal_id=event.proposal_id,  # type: ignore[arg-type]
            reason=event.reason or "user_declined",
            metadata={
                "decision_id": str(event.decision_id),
                "decided_at": (
                    event.decided_at.isoformat() if event.decided_at is not None else None
                ),
                "decided_via_channel": event.decided_via_channel,
            },
        )
        await self._message_bus.publish(translated)
        log.info(
            "approval.bus.translated_to_trading_rejected",
            proposal_id=str(event.proposal_id),
            decision_id=str(event.decision_id),
            reason=translated.reason,
        )

    async def _bridge_to_trading_timeout_handler(self, event: ApprovalProposalTimedOut) -> None:
        """Outbound bridge: ApprovalProposalTimedOut → trading.ProposalRejected.

        Collapses timeout to ``ProposalRejected(reason="approval_timeout")``
        sentinel — keeps T4's archive surface untouched (T4 has exactly
        one terminal handler for the rejected path; adding a separate
        ``ProposalApprovalTimedOut`` event class would force a T4
        register_subscriptions change).
        """
        from iguanatrader.contexts.trading.events import ProposalRejected
        from iguanatrader.shared.contextvars import tenant_id_var

        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            log.error(
                "approval.bus.bridge_skipped_no_tenant",
                bridge="timed_out",
                proposal_id=str(event.proposal_id),
            )
            return

        if getattr(event, "action_type", "entry") == "exit":
            # An EXIT approval that expired unanswered: position stays open,
            # no ProposalRejected. The advisor re-evaluates next tick.
            log.info(
                "approval.bus.exit_advice_expired",
                trade_id=str(event.trade_id),
                request_id=str(event.request_id),
            )
            return

        translated = ProposalRejected(
            tenant_id=tenant_id,
            proposal_id=event.proposal_id,  # type: ignore[arg-type]
            reason="approval_timeout",
            metadata={
                "request_id": str(event.request_id),
                "expired_at": (
                    event.expired_at.isoformat() if event.expired_at is not None else None
                ),
            },
        )
        await self._message_bus.publish(translated)
        log.info(
            "approval.bus.translated_to_trading_timed_out",
            proposal_id=str(event.proposal_id),
            request_id=str(event.request_id),
        )


__all__ = ["ApprovalService"]
