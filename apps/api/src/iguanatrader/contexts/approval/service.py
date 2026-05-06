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


class ApprovalService:
    """Coordinator for approval lifecycle + event emission."""

    def __init__(
        self,
        *,
        repository: ApprovalRepository,
        message_bus: MessageBus,
    ) -> None:
        self._repository = repository
        self._message_bus = message_bus

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


__all__ = ["ApprovalService"]
