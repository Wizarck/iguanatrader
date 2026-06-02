"""Repositories for observability-context tables.

Per the slice-2 :class:`BaseRepository` contract: each repository reads
its session lazily from
:data:`iguanatrader.shared.contextvars.session_var`. Domain code never
threads sessions through call stacks.

Three repositories — one per ORM model in :mod:`.models`:

- :class:`ApiCostEventRepository` — records LLM-call cost events;
  aggregates per tenant + period for budget gating + dashboard
  publication.
- :class:`ConfigChangeRepository` — records tenant-level config diffs.
- :class:`AuditLogRepository` — records audit events; supports both
  per-tenant (``tenant_id_var`` set) and cross-tenant
  (``tenant_id IS NULL``) scopes per design D8.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.contexts.observability.models import (
    ApiCostEvent,
    AuditLog,
    ConfigChange,
)
from iguanatrader.shared.contextvars import tenant_id_var
from iguanatrader.shared.kernel import BaseRepository

log = structlog.get_logger("iguanatrader.contexts.observability.repository")


class ApiCostEventRepository(BaseRepository):
    """Persistence + aggregation for :class:`ApiCostEvent`.

    Tenant scoping is enforced by the slice-3 listener — the repo does
    NOT explicitly filter by tenant in queries. The listener injects
    ``WHERE tenant_id = :ctx_tenant`` automatically; this repo's job is
    to express the per-period aggregation predicate.
    """

    async def insert(self, event: ApiCostEvent) -> None:
        """Add ``event`` to the current session.

        The slice-3 ``before_flush`` listener stamps ``tenant_id`` on
        the new instance from :data:`tenant_id_var`. Caller is
        responsible for the eventual ``await session.commit()``.
        """
        session = cast(AsyncSession, self.session)
        session.add(event)

    async def sum_cost_for_tenant_in_period(
        self,
        tenant_id: UUID,
        start: datetime,
        end: datetime,
    ) -> Decimal:
        """Sum of ``cost_usd`` over rows in ``[start, end)``.

        ``tenant_id`` is required as an explicit argument so this method
        can be called from the budget chokepoint with the correct value
        even when ``tenant_id_var`` is set; the slice-3 listener still
        applies its own filter, so the result is the intersection
        (defence-in-depth).
        """
        session = cast(AsyncSession, self.session)
        stmt = (
            select(func.coalesce(func.sum(ApiCostEvent.cost_usd), 0))
            .where(ApiCostEvent.tenant_id == tenant_id)
            .where(ApiCostEvent.created_at >= start)
            .where(ApiCostEvent.created_at < end)
        )
        result = await session.execute(stmt)
        total = result.scalar_one()
        return Decimal(total) if not isinstance(total, Decimal) else total

    async def query_by_tenant_and_period(
        self,
        tenant_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[ApiCostEvent]:
        """Return rows in ``[start, end)`` ordered by ``created_at`` ascending."""
        session = cast(AsyncSession, self.session)
        stmt = (
            select(ApiCostEvent)
            .where(ApiCostEvent.tenant_id == tenant_id)
            .where(ApiCostEvent.created_at >= start)
            .where(ApiCostEvent.created_at < end)
            .order_by(ApiCostEvent.created_at)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class ConfigChangeRepository(BaseRepository):
    """Persistence for :class:`ConfigChange` (FR47)."""

    async def insert(self, change: ConfigChange) -> None:
        """Add ``change`` to the current session."""
        session = cast(AsyncSession, self.session)
        session.add(change)

    async def query_by_tenant_and_period(
        self,
        tenant_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[ConfigChange]:
        """Return rows in ``[start, end)`` ordered by ``created_at`` ascending."""
        session = cast(AsyncSession, self.session)
        stmt = (
            select(ConfigChange)
            .where(ConfigChange.tenant_id == tenant_id)
            .where(ConfigChange.created_at >= start)
            .where(ConfigChange.created_at < end)
            .order_by(ConfigChange.created_at)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class AuditLogRepository(BaseRepository):
    """Persistence for :class:`AuditLog` — supports per-tenant + cross-tenant.

    Per design D8: ``insert_global`` writes a row with ``tenant_id=NULL``
    for ops-global events; ``insert_for_tenant`` writes a per-tenant row
    (the slice-3 listener stamps ``tenant_id`` from
    :data:`tenant_id_var`). Read methods mirror the split.
    """

    async def insert(self, entry: AuditLog) -> None:
        """Add ``entry`` to the current session, stamping the tenant.

        #40: ``AuditLog.tenant_id`` is nullable and the slice-3 listener
        does NOT stamp it (the column is intentionally optional for
        ops-global rows). That means a *tenant-scoped* event whose
        ``tenant_id`` the caller forgot to set would silently land as a
        GLOBAL row (NULL) — losing attribution and polluting the global
        audit feed. Here we bind the active ``tenant_id_var`` when the
        entry has no tenant and a tenant context is in scope. A genuinely
        global row (no tenant context) is still allowed but logged, so an
        unstamped global write is visible rather than silent. Callers that
        KNOW their intent should prefer :meth:`insert_for_tenant` /
        :meth:`insert_global`.
        """
        session = cast(AsyncSession, self.session)
        if entry.tenant_id is None:
            ambient = tenant_id_var.get()
            if ambient is not None:
                entry.tenant_id = ambient
            else:
                log.info("observability.audit_log.global_row", event=entry.event)
        session.add(entry)

    async def insert_for_tenant(self, entry: AuditLog) -> None:
        """Insert a per-tenant audit row, REQUIRING a resolvable tenant.

        Raises ``LookupError`` if the entry has no tenant and none is bound
        on :data:`tenant_id_var` — a tenant-scoped audit event must never
        silently degrade to a global row.
        """
        if entry.tenant_id is None:
            ambient = tenant_id_var.get()
            if ambient is None:
                raise LookupError(
                    "insert_for_tenant requires a tenant (entry.tenant_id unset and "
                    "tenant_id_var not bound)"
                )
            entry.tenant_id = ambient
        cast(AsyncSession, self.session).add(entry)

    async def insert_global(self, entry: AuditLog) -> None:
        """Insert an intentional ops-global (``tenant_id=NULL``) audit row."""
        entry.tenant_id = None
        cast(AsyncSession, self.session).add(entry)

    async def query_global(
        self,
        start: datetime,
        end: datetime,
    ) -> list[AuditLog]:
        """Return ``tenant_id IS NULL`` rows in ``[start, end)`` ascending."""
        session = cast(AsyncSession, self.session)
        stmt = (
            select(AuditLog)
            .where(AuditLog.tenant_id.is_(None))
            .where(AuditLog.created_at >= start)
            .where(AuditLog.created_at < end)
            .order_by(AuditLog.created_at)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def query_for_tenant(
        self,
        tenant_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[AuditLog]:
        """Return rows for ``tenant_id`` in ``[start, end)`` ascending."""
        session = cast(AsyncSession, self.session)
        stmt = (
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .where(AuditLog.created_at >= start)
            .where(AuditLog.created_at < end)
            .order_by(AuditLog.created_at)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


__all__ = [
    "ApiCostEventRepository",
    "AuditLogRepository",
    "ConfigChangeRepository",
]
