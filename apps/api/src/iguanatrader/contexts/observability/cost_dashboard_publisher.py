"""Periodic 5-minute cost-snapshot publisher (NFR-O4).

Aggregates :class:`ApiCostEvent` rows from the last
:data:`COST_SNAPSHOT_CADENCE_SECONDS` (default 300s) per tenant and
emits :class:`CostSnapshotEvent` on the shared :class:`MessageBus`.
The SSE endpoint at ``GET /api/v1/stream/costs/snapshots`` subscribes
and forwards to dashboard clients.

Slice O1 plants the publisher logic + the snapshot-building helper.
The actual scheduler that calls :func:`publish_snapshot` every 5
minutes is owned by slice O2 (``orchestration-scheduler-routines``);
until then operators run :func:`publish_snapshot` ad-hoc / from a
small loop in tests.

Per design D4 / NFR-O4 wording: "every 5min in active session". The
cadence value is parametrised so tests can use shorter intervals.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.contexts.observability.events import CostSnapshotEvent
from iguanatrader.contexts.observability.models import ApiCostEvent
from iguanatrader.persistence.models import Tenant
from iguanatrader.shared.contextvars import (
    session_var,
    with_tenant_context,
)
from iguanatrader.shared.messagebus import MessageBus
from iguanatrader.shared.time import now

log = structlog.get_logger("iguanatrader.contexts.observability.cost_dashboard_publisher")


def _cadence_seconds() -> int:
    """Resolved cadence — env override or default 300s."""
    raw = os.getenv("IGUANATRADER_COST_SNAPSHOT_CADENCE_SECONDS")
    if raw is not None:
        try:
            parsed = int(raw)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return 300


COST_SNAPSHOT_CADENCE_SECONDS: int = _cadence_seconds()


async def _aggregate_tenant_window(
    tenant_id: UUID,
    start: datetime,
    end: datetime,
) -> CostSnapshotEvent:
    """Build a :class:`CostSnapshotEvent` for ``tenant_id`` in ``[start, end)``.

    Sums ``cost_usd`` overall + per provider + per model. Counts total
    calls + cached calls. The slice-3 listener auto-filters
    ``api_cost_events`` to the bound tenant; we still pass the tenant
    in the WHERE clause as defence-in-depth.
    """
    sess = session_var.get()
    if sess is None:
        raise LookupError(
            "session_var unset — cost_dashboard_publisher.publish_snapshot "
            "must be invoked inside a session-bound context."
        )
    session = cast(AsyncSession, sess)

    stmt = (
        select(ApiCostEvent)
        .where(ApiCostEvent.tenant_id == tenant_id)
        .where(ApiCostEvent.created_at >= start)
        .where(ApiCostEvent.created_at < end)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    total_cost = Decimal("0")
    cached_calls = 0
    by_provider: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_model: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for row in rows:
        cost = row.cost_usd if isinstance(row.cost_usd, Decimal) else Decimal(str(row.cost_usd))
        total_cost += cost
        if row.cached:
            cached_calls += 1
        by_provider[row.provider] += cost
        by_model[row.model] += cost

    return CostSnapshotEvent(
        tenant_id=tenant_id,
        bucket_start=start,
        bucket_end=end,
        total_cost_usd=total_cost,
        total_calls=len(rows),
        cached_calls=cached_calls,
        by_provider=dict(by_provider),
        by_model=dict(by_model),
    )


async def _list_tenant_ids() -> list[UUID]:
    """Read all (non-soft-deleted) tenant ids — system context.

    The :class:`Tenant` mapping is non-tenant-scoped so the slice-3
    listener does not filter; we still iterate explicitly here so the
    publisher works without a bound ``tenant_id_var``.
    """
    sess = session_var.get()
    if sess is None:
        return []
    session = cast(AsyncSession, sess)
    stmt = select(Tenant.id).where(Tenant.deleted_at.is_(None))
    result = await session.execute(stmt)
    rows = result.all()
    out: list[UUID] = []
    for row in rows:
        raw = row[0]
        out.append(raw if isinstance(raw, UUID) else UUID(str(raw)))
    return out


async def publish_snapshot(
    bus: MessageBus,
    *,
    cadence_seconds: int | None = None,
    at: datetime | None = None,
) -> list[CostSnapshotEvent]:
    """Emit one :class:`CostSnapshotEvent` per tenant for the trailing window.

    Iterates every tenant; for each, aggregates the last
    ``cadence_seconds`` of cost events and publishes the snapshot.
    Returns the list of emitted events for caller convenience (tests
    + the SSE endpoint inspect the structured payload).
    """
    cadence = cadence_seconds or COST_SNAPSHOT_CADENCE_SECONDS
    when = at or now()
    start = when - timedelta(seconds=cadence)

    tenant_ids = await _list_tenant_ids()
    snapshots: list[CostSnapshotEvent] = []
    for tenant_id in tenant_ids:
        async with with_tenant_context(tenant_id):
            snapshot = await _aggregate_tenant_window(tenant_id, start, when)
        await bus.publish(snapshot)
        snapshots.append(snapshot)
        log.info(
            "observability.cost.snapshot_published",
            tenant_id=str(tenant_id),
            bucket_start=start.isoformat(),
            bucket_end=when.isoformat(),
            total_cost_usd=str(snapshot.total_cost_usd),
            total_calls=snapshot.total_calls,
        )
    return snapshots


__all__ = [
    "COST_SNAPSHOT_CADENCE_SECONDS",
    "publish_snapshot",
]
