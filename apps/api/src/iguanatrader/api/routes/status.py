"""GET /api/v1/status — daemon status snapshot.

Slice ``dual-daemon-mode-toggle-and-reconcile``. Session-auth (any
logged-in user; not admin-gated — surfacing per-mode liveness is read-
only and operationally low-risk). Mirrors what the web layout's
persistent mode chips render against on every 5s poll.

Stale-heartbeat detection (>30s since last heartbeat) collapses to
``ib_connected=false`` regardless of the persisted heartbeat row value
— a daemon that has crashed in a way that prevents the heartbeat cron
from running would otherwise show its last persisted state forever.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.status import DaemonStatusOut, StatusResponse
from iguanatrader.contexts.trading.repository import TradingModeRepository
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger("iguanatrader.api.routes.status")

router = APIRouter(prefix="/status", tags=["status"])


_STALE_HEARTBEAT_SECS = 30


@router.get("", response_model=StatusResponse)
async def get_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatusResponse:
    """Return the per-mode daemon status snapshot for the current tenant."""
    session_var.set(db)

    repo = TradingModeRepository()
    rows = await repo.load_daemon_status_summary(user.tenant_id)

    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(seconds=_STALE_HEARTBEAT_SECS)
    daemons = [
        DaemonStatusOut(
            mode=row.mode,
            enabled=row.enabled,
            ib_connected=(
                row.ib_connected
                and row.last_heartbeat_at is not None
                and row.last_heartbeat_at > stale_cutoff
            ),
            last_heartbeat_at=row.last_heartbeat_at,
            last_fill_at=row.last_fill_at,
            pending_proposals_count=row.pending_proposals_count,
        )
        for row in rows
    ]

    log.info(
        "api.status.read",
        tenant_id=str(user.tenant_id),
        daemon_count=len(daemons),
    )

    return StatusResponse(daemons=daemons, fetched_at=now)


__all__ = ["router"]
