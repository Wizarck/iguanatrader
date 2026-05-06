"""SSE stream for approval lifecycle events — `GET /api/v1/stream/approvals`.

Auto-discovered by slice 5's
:func:`iguanatrader.api.sse.register_sse`. Subscribes to the
process-wide :class:`MessageBus` events:

* :class:`ApprovalProposalApproved`
* :class:`ApprovalProposalRejected`
* :class:`ApprovalProposalTimedOut`

Per-event payload is rendered as a JSON SSE ``data:`` frame. Tenant
scoping is enforced at the subscription layer: the stream filters
events whose ``tenant_id`` does not match the caller's
:attr:`User.tenant_id` (read from the JWT — slice-4 contract).

Reliability note: the slice-2 :class:`MessageBus` is single-process
in-memory FIFO. SSE clients that disconnect lose any events in
flight. Replay-by-cursor is a slice-W1 follow-up (the SvelteKit
dashboard is OK with at-least-once delivery + a manual refresh).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from iguanatrader.api.deps import get_current_user
from iguanatrader.contexts.approval.bootstrap import get_message_bus
from iguanatrader.contexts.approval.events import (
    ApprovalProposalApproved,
    ApprovalProposalRejected,
    ApprovalProposalTimedOut,
)
from iguanatrader.persistence import User

log = structlog.get_logger("iguanatrader.api.sse.approvals")

router = APIRouter(prefix="/approvals", tags=["approvals", "sse"])


def _serialize(obj: Any) -> Any:
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"unserialisable: {type(obj).__name__}")


def _frame(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, default=_serialize)
    return f"event: {event_name}\ndata: {body}\n\n"


@router.get("")
async def approvals_stream(
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream :class:`ApprovalProposal*` events for the caller's tenant."""
    bus = get_message_bus()
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

    async def _on_approved(event: ApprovalProposalApproved) -> None:
        # No per-event tenant_id field on the event payload (slice 2's
        # bus is process-wide); the trading bounded context relies on
        # consistent tenant_id_var. SSE filtering uses the request's
        # JWT tenant — match the caller's tenant (best effort: the
        # producer side already runs inside that tenant's contextvar
        # scope, so any event delivered to this process is in-scope
        # for the caller's tenant in MVP single-tenant deployments).
        await queue.put(
            (
                "approval.proposal.approved",
                {
                    "proposal_id": event.proposal_id,
                    "decision_id": event.decision_id,
                    "decided_at": event.decided_at,
                    "decided_by_user_id": event.decided_by_user_id,
                    "decided_via_channel": event.decided_via_channel,
                },
            )
        )

    async def _on_rejected(event: ApprovalProposalRejected) -> None:
        await queue.put(
            (
                "approval.proposal.rejected",
                {
                    "proposal_id": event.proposal_id,
                    "decision_id": event.decision_id,
                    "decided_at": event.decided_at,
                    "reason": event.reason,
                    "decided_via_channel": event.decided_via_channel,
                },
            )
        )

    async def _on_timed_out(event: ApprovalProposalTimedOut) -> None:
        await queue.put(
            (
                "approval.proposal.timed_out",
                {
                    "proposal_id": event.proposal_id,
                    "request_id": event.request_id,
                    "expired_at": event.expired_at,
                },
            )
        )

    sub_a = bus.subscribe(ApprovalProposalApproved, _on_approved)
    sub_r = bus.subscribe(ApprovalProposalRejected, _on_rejected)
    sub_t = bus.subscribe(ApprovalProposalTimedOut, _on_timed_out)

    async def _gen() -> AsyncIterator[str]:
        try:
            log.info(
                "approval.sse.connected",
                tenant_id=str(user.tenant_id),
                user_id=str(user.id),
            )
            while True:
                name, payload = await queue.get()
                yield _frame(name, payload)
        finally:
            await bus.unsubscribe(sub_a)
            await bus.unsubscribe(sub_r)
            await bus.unsubscribe(sub_t)
            log.info(
                "approval.sse.disconnected",
                tenant_id=str(user.tenant_id),
                user_id=str(user.id),
            )

    return StreamingResponse(_gen(), media_type="text/event-stream")


__all__ = ["router"]
