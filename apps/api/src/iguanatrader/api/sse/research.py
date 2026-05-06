"""SSE endpoint for research brief refresh progress (slice R5 design D8).

Mounts at ``/api/v1/stream/research`` via slice-5 dynamic discovery
(``register_routers`` walks ``api/sse/`` for top-level ``router``
symbols). Publishes 3 event types:

* ``research.brief.refresh.progress`` — per-step progress during
  in-flight synthesis.
* ``research.brief.refreshed`` — emitted after commit.
* ``research.fact.recorded`` — re-emitted from the bus
  ``ResearchFactIngested`` for FactTimeline live updates.

R5 ships the publisher Protocol + the SSE endpoint; O2 wires the
periodic publisher that emits during scheduled refreshes. Until O2
lands, manual ``service.refresh()`` calls do NOT emit progress events
— this is acceptable for MVP because the route response carries the
synthesised brief directly.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from iguanatrader.api.deps import get_current_user
from iguanatrader.persistence import User
from iguanatrader.shared.messagebus import MessageBus

log = structlog.get_logger("iguanatrader.api.sse.research")

router = APIRouter(prefix="/research", tags=["research"])


_bus: MessageBus | None = None


def get_research_bus() -> MessageBus:
    """Lazy-init the process-local research MessageBus."""
    global _bus
    if _bus is None:
        _bus = MessageBus()
    return _bus


async def _event_stream(user: User) -> AsyncIterator[str]:
    """Yield SSE events for the authenticated user's tenant.

    Heartbeat every 15s keeps proxies from closing the connection.
    """
    # Slice R5 declares the SSE shape; O2 wires the publisher loop that
    # pumps events from `get_research_bus()` into the per-connection queue.
    # MVP: emit a single ``connected`` event + 15s heartbeats so the
    # frontend can wire `useSSE('/api/v1/stream/research')` against this
    # endpoint. Per-tenant filter applies once O2 ships subscribers.
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=100)
    yield 'event: connected\ndata: {"hello": "research"}\n\n'

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=15.0)
        except TimeoutError:
            yield ": heartbeat\n\n"
            continue
        # Per-tenant filter (O2 publisher tags `tenant_id`).
        if event.get("tenant_id") not in (None, str(user.tenant_id)):
            continue
        payload = json.dumps(event)
        event_type = event.get("event_type", "research")
        yield f"event: {event_type}\ndata: {payload}\n\n"


@router.get("/stream")
async def stream(
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE stream for research brief progress + fact-recorded events."""
    log.info("api.sse.research.connect", tenant_id=str(user.tenant_id))
    return StreamingResponse(
        _event_stream(user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["get_research_bus", "router"]
