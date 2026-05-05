"""Server-Sent Events endpoint for cost-snapshot streaming (NFR-O4).

Mounted at ``/api/v1/stream/costs/snapshots`` via the slice-5 SSE
discovery loop. Subscribers receive
:class:`iguanatrader.contexts.observability.events.CostSnapshotEvent`
serialised as :class:`CostSnapshotDTO` JSON payloads, one event per
SSE message.

Slice O1 plants the endpoint shape + the per-tenant filter (the SSE
stream only forwards events whose ``tenant_id`` matches the
authenticated user's). Slice O2 wires the periodic publisher that
emits one snapshot per tenant every 5 minutes; until then operators
can call :func:`iguanatrader.contexts.observability.cost_dashboard_publisher.publish_snapshot`
manually + observe one-shot streams.

Per design D6 + slice-5 dynamic discovery contract: this module
exports a top-level ``router: APIRouter``; no edit to ``app.py`` is
needed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from iguanatrader.api.deps import get_current_user
from iguanatrader.api.dtos.costs import CostSnapshotDTO
from iguanatrader.contexts.observability.events import CostSnapshotEvent
from iguanatrader.persistence import User
from iguanatrader.shared.messagebus import MessageBus, Subscription

log = structlog.get_logger("iguanatrader.api.sse.costs")

router = APIRouter(prefix="/costs", tags=["costs"])


#: Process-local :class:`MessageBus` used for cost-snapshot fanout.
#: Slice O2 will move this to a shared FastAPI app-state container so
#: multiple subscribers (SSE + audit log writer + OTEL meter) can share
#: a single bus. MVP: one bus, lazy-initialised on first SSE connect.
_bus: MessageBus | None = None


def get_cost_bus() -> MessageBus:
    """Lazy-init the process-local cost MessageBus.

    Tests reset via :func:`reset_cost_bus_for_tests`.
    """
    global _bus
    if _bus is None:
        _bus = MessageBus()
    return _bus


def reset_cost_bus_for_tests() -> None:
    """Drop the process-local cost MessageBus. Test-only helper."""
    global _bus
    _bus = None


def _snapshot_to_dto(event: CostSnapshotEvent) -> CostSnapshotDTO:
    """Project a bus event onto its API DTO (one-to-one fields)."""
    return CostSnapshotDTO(
        tenant_id=event.tenant_id,
        bucket_start=event.bucket_start,
        bucket_end=event.bucket_end,
        total_cost_usd=event.total_cost_usd,
        total_calls=event.total_calls,
        cached_calls=event.cached_calls,
        by_provider=event.by_provider,
        by_model=event.by_model,
    )


async def _stream_for_user(user: User) -> AsyncIterator[bytes]:
    """SSE stream — one ``data:`` line per :class:`CostSnapshotEvent` for ``user.tenant_id``.

    Subscribes to the cost bus on entry, unsubscribes on
    :class:`asyncio.CancelledError` (client disconnect).
    """
    bus = get_cost_bus()
    queue: asyncio.Queue[CostSnapshotEvent] = asyncio.Queue()

    async def _on_snapshot(event: CostSnapshotEvent) -> None:
        if event.tenant_id == user.tenant_id:
            await queue.put(event)

    sub: Subscription[CostSnapshotEvent] = bus.subscribe(
        CostSnapshotEvent, _on_snapshot
    )

    try:
        while True:
            event = await queue.get()
            dto = _snapshot_to_dto(event)
            payload = dto.model_dump_json()
            yield f"data: {payload}\n\n".encode("utf-8")
    except asyncio.CancelledError:
        log.info(
            "observability.cost.snapshot_stream_cancelled",
            tenant_id=str(user.tenant_id),
            user_id=str(user.id),
        )
        raise
    finally:
        await bus.unsubscribe(sub)


@router.get("/snapshots")
async def stream_cost_snapshots(
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE stream of cost-snapshot events filtered to the caller's tenant."""
    return StreamingResponse(
        _stream_for_user(user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = [
    "get_cost_bus",
    "reset_cost_bus_for_tests",
    "router",
]
