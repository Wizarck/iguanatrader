"""SQLAlchemy adapter for the ``trailing_stop_audit`` table.

Slice ``orchestration-trailing-stops-cron``. Kept separate from
:class:`RiskRepository` because the audit table is single-purpose
(stop-history log read by the sweep service) and does not participate
in the :class:`RiskRepositoryPort` contract — the sweep is a
post-fill service, not part of the pre-trade evaluation surface.

Tenant scoping comes from the slice-3 ``tenant_listener`` reading
:data:`tenant_id_var`; this module does NOT issue
``WHERE tenant_id = ?`` manually.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.contexts.risk.orm import TrailingStopAuditORM


class TrailingStopAuditRepository:
    """Read/write surface for the ``trailing_stop_audit`` table."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        # Audit #29: ``session`` is OPTIONAL. When omitted, each method
        # resolves the active session from ``session_var`` at call time, so a
        # single shared instance rides whichever per-tick cron session the
        # sweep unit-of-work wrapper binds (the stop-hit + trailing sweeps now
        # each run on their own fresh per-tick session). Explicit callers
        # (tests, request scope) keep passing one and are unaffected.
        self._explicit_session = session

    @property
    def _session(self) -> AsyncSession:
        if self._explicit_session is not None:
            return self._explicit_session
        from iguanatrader.shared.contextvars import session_var

        sess = session_var.get()
        if sess is None:
            raise LookupError(
                "TrailingStopAuditRepository has no session: pass session=... "
                "or bind session_var (per-tick cron scope / request scope)."
            )
        return cast("AsyncSession", sess)

    async def add_row(
        self,
        *,
        tenant_id: UUID,
        trade_id: UUID,
        swept_at: datetime,
        old_stop: Decimal,
        new_stop: Decimal,
        highest_close_since_entry: Decimal,
        atr: Decimal,
        bars_evaluated: int,
    ) -> UUID:
        """INSERT a new audit row. Returns the generated id."""
        row_id = uuid.uuid4()
        row = TrailingStopAuditORM(
            id=row_id,
            tenant_id=tenant_id,
            trade_id=trade_id,
            swept_at=swept_at,
            old_stop=old_stop,
            new_stop=new_stop,
            highest_close_since_entry=highest_close_since_entry,
            atr=atr,
            bars_evaluated=bars_evaluated,
        )
        self._session.add(row)
        await self._session.flush()
        return row_id

    async def get_latest_for_trade(self, trade_id: UUID) -> TrailingStopAuditORM | None:
        """Return the most-recent audit row for ``trade_id`` (or None)."""
        stmt = (
            select(TrailingStopAuditORM)
            .where(TrailingStopAuditORM.trade_id == trade_id)
            .order_by(TrailingStopAuditORM.swept_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()


__all__ = ["TrailingStopAuditRepository"]
