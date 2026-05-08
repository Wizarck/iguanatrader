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
from iguanatrader.contexts.approval.errors import ApprovalNotFoundError
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
        proposal_id: UUID,
        channels: Sequence[str],
        timeout_seconds: int,
    ) -> ApprovalRequestRow:
        """Persist a new approval request + log creation.

        Fan-out to channels is the channels' responsibility (the
        service hands the row to each channel adapter via the route /
        dispatcher). This method is the audit-write entry point only.
        """
        row = await self._repository.create_request(
            proposal_id=proposal_id,
            delivered_to_channels=list(channels),
            timeout_seconds=timeout_seconds,
        )
        log.info(
            "approval.request.created",
            request_id=str(row.id),
            proposal_id=str(proposal_id),
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
        latency_ms = int(
            max(
                (decided_at - request.created_at).total_seconds() * 1000,
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
        event: Any
        if outcome == "granted":
            event = ApprovalProposalApproved(
                proposal_id=request.proposal_id,
                decision_id=decision.id,
                decided_at=decided_at,
                decided_by_user_id=decision.decided_by_user_id,
                decided_via_channel=decision.decided_via_channel,
            )
        elif outcome == "rejected":
            event = ApprovalProposalRejected(
                proposal_id=request.proposal_id,
                decision_id=decision.id,
                decided_at=decided_at,
                reason=reason,
                decided_via_channel=decision.decided_via_channel,
            )
        else:
            event = ApprovalProposalTimedOut(
                proposal_id=request.proposal_id,
                request_id=request.id,
                expired_at=request.expires_at,
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

        from iguanatrader.contexts.trading.events import ApprovalRequested

        target_bus.subscribe(
            ApprovalRequested,
            self._approval_requested_handler,
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

    async def _bridge_to_trading_approved_handler(self, event: ApprovalProposalApproved) -> None:
        """Outbound bridge: ApprovalProposalApproved → trading.ProposalApproved.

        Tenant id is resolved from :data:`tenant_id_var` (slice 2 D2);
        P1 events do not carry tenant_id (the audit row is tenant-scoped
        by row-level scoping, not by event payload). If the ContextVar
        is unset (test outside request scope) we log and skip rather
        than emit a tenant-less event.
        """
        from iguanatrader.contexts.trading.events import ProposalApproved
        from iguanatrader.shared.contextvars import tenant_id_var

        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            log.error(
                "approval.bus.bridge_skipped_no_tenant",
                bridge="approved",
                proposal_id=str(event.proposal_id),
            )
            return

        translated = ProposalApproved(
            tenant_id=tenant_id,
            proposal_id=event.proposal_id,  # type: ignore[arg-type]
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
