"""SSE endpoint streaming ``risk.*`` MessageBus events.

Mounted at ``/api/v1/stream/risk/events`` by the slice-5 dynamic
discovery loop. Each connected client gets its own
:class:`asyncio.Queue` subscription on the process-local
:class:`MessageBus`; the handler drains the queue into Server-Sent
Events as JSON-encoded :class:`RiskEventPayload` envelopes.

NOTE on the bus singleton: slice 2's :class:`MessageBus` is in-process
+ single-instance per Python interpreter. K1 ships a
:func:`get_risk_bus` accessor that lazily constructs the bus on first
call. Tests can monkey-patch this accessor to inject a fake bus.
Slice O1 will replace the lazy singleton with an explicit lifespan-
managed object on ``app.state.risk_bus``; until then, the singleton
is the contract.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from iguanatrader.api.deps import get_current_user
from iguanatrader.contexts.risk.events import (
    RiskKillSwitchActivated,
    RiskKillSwitchDeactivated,
    RiskProposalAccepted,
    RiskProposalOverrideRequired,
    RiskProposalRejected,
)
from iguanatrader.persistence import User
from iguanatrader.shared.messagebus import Event, MessageBus, Subscription

log = structlog.get_logger("iguanatrader.api.sse.risk")

router = APIRouter(prefix="/risk", tags=["risk", "sse"])

#: Lazy module-level singleton — replaced by lifespan wiring in slice O1.
_BUS: MessageBus | None = None


def get_risk_bus() -> MessageBus:
    """Return the process-local risk :class:`MessageBus` (lazy)."""
    global _BUS
    if _BUS is None:
        _BUS = MessageBus()
    return _BUS


def _serialise_event(event: object) -> dict[str, Any]:
    """Render a risk event dataclass as a JSON-friendly dict.

    Map dataclass fields → ``RiskEventPayload`` envelope shape. Decimal
    values are coerced to ``str`` so :func:`json.dumps` accepts them
    without a custom encoder.
    """

    def coerce(value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    if isinstance(event, RiskProposalAccepted):
        return {
            "kind": "risk.proposal.accepted",
            "occurred_at": coerce(event.occurred_at),
            "tenant_id": coerce(event.tenant_id),
            "proposal_id": coerce(event.proposal_id),
            "evaluation_id": coerce(event.evaluation_id),
            "outcome": "allow",
        }
    if isinstance(event, RiskProposalRejected):
        return {
            "kind": "risk.proposal.rejected",
            "occurred_at": coerce(event.occurred_at),
            "tenant_id": coerce(event.tenant_id),
            "proposal_id": coerce(event.proposal_id),
            "evaluation_id": coerce(event.evaluation_id),
            "cap_type_breached": event.cap_type_breached,
            "current_pct": coerce(event.current_pct),
            "outcome": "reject",
        }
    if isinstance(event, RiskProposalOverrideRequired):
        return {
            "kind": "risk.proposal.override_required",
            "occurred_at": coerce(event.occurred_at),
            "tenant_id": coerce(event.tenant_id),
            "proposal_id": coerce(event.proposal_id),
            "override_id": coerce(event.override_id),
            "actor_user_id": coerce(event.authorised_by_user_id),
        }
    if isinstance(event, RiskKillSwitchActivated):
        return {
            "kind": "risk.kill_switch.activated",
            "occurred_at": coerce(event.occurred_at),
            "tenant_id": coerce(event.tenant_id),
            "source": event.source,
            "actor_user_id": coerce(event.actor_user_id),
            "reason": event.reason,
        }
    if isinstance(event, RiskKillSwitchDeactivated):
        return {
            "kind": "risk.kill_switch.deactivated",
            "occurred_at": coerce(event.occurred_at),
            "tenant_id": coerce(event.tenant_id),
            "source": event.source,
            "actor_user_id": coerce(event.actor_user_id),
            "reason": event.reason,
        }
    raise TypeError(f"unsupported event type: {type(event)!r}")


@router.get("/events")
async def stream_risk_events(
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Open a long-lived SSE connection streaming ``risk.*`` events.

    The frontend's EventSource reads this endpoint and discriminates
    on the ``kind`` field. Each event is a single SSE record:

    ``data: {"kind":"risk.proposal.accepted",...}\\n\\n``

    The connection blocks indefinitely while the queue drains; a
    client disconnect propagates as :class:`asyncio.CancelledError` to
    the generator and the subscription is unwound by the bus.
    """
    bus = get_risk_bus()

    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def _enqueue(event: Any) -> None:
        await queue.put(event)

    subs: list[Subscription[Event]] = [
        cast("Subscription[Event]", bus.subscribe(RiskProposalAccepted, _enqueue)),
        cast("Subscription[Event]", bus.subscribe(RiskProposalRejected, _enqueue)),
        cast(
            "Subscription[Event]",
            bus.subscribe(RiskProposalOverrideRequired, _enqueue),
        ),
        cast("Subscription[Event]", bus.subscribe(RiskKillSwitchActivated, _enqueue)),
        cast("Subscription[Event]", bus.subscribe(RiskKillSwitchDeactivated, _enqueue)),
    ]

    log.info(
        "risk.sse.connected",
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
    )

    async def _stream() -> AsyncIterator[bytes]:
        try:
            while True:
                event = await queue.get()
                payload = _serialise_event(event)
                # Tenant filtering: only forward events for the
                # caller's tenant. Other tenants' events are silently
                # dropped; this is the SSE-level tenant boundary.
                if payload.get("tenant_id") != str(user.tenant_id):
                    continue
                yield f"data: {json.dumps(payload)}\n\n".encode()
        finally:
            for sub in subs:
                await bus.unsubscribe(sub)
            log.info(
                "risk.sse.disconnected",
                tenant_id=str(user.tenant_id),
                user_id=str(user.id),
            )

    return StreamingResponse(_stream(), media_type="text/event-stream")


__all__ = ["get_risk_bus", "router"]
