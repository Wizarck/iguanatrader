"""Admin endpoints for the research-ingest scheduler (slice I7).

Auto-discovered by :func:`iguanatrader.api.routes.register_routers`.
Surface is intentionally narrow:

* ``GET /api/v1/admin/ingest-runs`` — list the recent ``IngestRun``
  rows for the caller's tenant. Supports ``status=ok|error|started``
  + ``source_id=<id>`` filters + ``limit`` (default 50, max 200).

Cancel + retry endpoints are future-work — APScheduler exposes a job
``remove_job`` surface but lift-and-shift integration into the
existing :class:`APSchedulerAdapter` belongs in a separate slice
because it needs the live scheduler handle, not just the DB history.

Auth: any authenticated user can see *their tenant's* runs; the
listener auto-scopes the SELECT by tenant_id so no cross-tenant
leak is possible. The `god_admin` role is reserved for cross-tenant
debug surfaces (not exposed yet).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.contexts.research.models import IngestRun
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var

log = structlog.get_logger("iguanatrader.api.routes.admin_ingest")

router = APIRouter(prefix="/admin/ingest-runs", tags=["admin"])


class IngestRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_id: str
    symbol: str | None
    invoked_by: str
    status: str
    facts_inserted: int
    error_detail: str | None
    started_at: str
    finished_at: str | None


@router.get("", response_model=list[IngestRunResponse])
async def list_ingest_runs(
    status: str | None = Query(
        default=None,
        pattern=r"^(started|ok|error|cancelled)$",
        description="Filter by status. Omit for all.",
    ),
    source_id: str | None = Query(default=None, description="Filter by research_sources.id."),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[IngestRunResponse]:
    """List recent ``IngestRun`` rows for the caller's tenant."""
    log.info(
        "api.admin.ingest_runs.list",
        status=status,
        source_id=source_id,
        limit=limit,
    )
    session_var.set(db)

    stmt = select(IngestRun).order_by(IngestRun.started_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(IngestRun.status == status)
    if source_id is not None:
        stmt = stmt.where(IngestRun.source_id == source_id)

    rows = (await db.execute(stmt)).scalars().all()
    return [
        IngestRunResponse(
            id=str(row.id),
            source_id=row.source_id,
            symbol=row.symbol,
            invoked_by=row.invoked_by,
            status=row.status,
            facts_inserted=row.facts_inserted,
            error_detail=row.error_detail,
            started_at=row.started_at.isoformat(),
            finished_at=row.finished_at.isoformat() if row.finished_at else None,
        )
        for row in rows
    ]


__all__ = ["router"]
