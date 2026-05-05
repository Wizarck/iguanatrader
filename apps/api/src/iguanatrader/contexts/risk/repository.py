"""SQLAlchemy adapter implementing :class:`RiskRepositoryPort`.

Per slice K1 design + tasks 4.1: thin wrapper around an
:class:`AsyncSession` (the FastAPI request-scoped session — slice 5
will move it under ``session_var`` once that lands as a SQLAlchemy
type). Tenant scoping is handled by the slice-3 ``tenant_listener`` —
this repository does NOT manually filter by tenant_id; it relies on
the global listener that reads
:data:`iguanatrader.shared.contextvars.tenant_id_var`.

All write operations are append-only EXCEPT
:meth:`update_kill_switch_cache` which UPDATEs the single
``kill_switch_state`` row (kill-switch cache is the explicit exception
to the global append-only invariant — see slice K1 design D4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.contexts.risk.models import (
    CapType,
    ConfirmationChain,
    Decision,
    KillSwitchSource,
    RiskState,
)
from iguanatrader.contexts.risk.orm import (
    KillSwitchEventORM,
    KillSwitchStateORM,
    RiskEvaluationORM,
    RiskOverrideORM,
)
from iguanatrader.contexts.risk.ports import RiskRepositoryPort


class RiskRepository(RiskRepositoryPort):
    """Concrete SQLAlchemy adapter for the risk persistence surface."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_risk_state(self, tenant_id: UUID) -> RiskState:
        """Return a placeholder :class:`RiskState` until T1 + O1 land.

        K1's bridge contract (per design + ``docs/openspec-slice.md``)
        says risk state is derived from equity snapshots (O1) + open
        positions (T1). Both are out of scope for K1; this method
        returns a neutral default so the engine can be exercised in
        unit + integration tests against an empty state.

        Real implementation lands when:

        * O1 ships ``equity_snapshots`` + the daily P&L roll-up.
        * T1 ships the open-positions count query.

        Until then the service layer can override this method (or
        the test fixture can swap an in-memory port impl).
        """
        return RiskState(capital=Decimal(0))

    async def save_evaluation(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        decision: Decision,
        created_at: datetime,
    ) -> UUID:
        """INSERT a row into ``risk_evaluations``; return the new id."""
        eval_id = uuid.uuid4()
        row = RiskEvaluationORM(
            id=eval_id,
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            outcome=decision.outcome,
            cap_type_breached=decision.cap_type_breached,
            current_pct=decision.current_pct,
            state_snapshot=dict(decision.state_snapshot),
            clip_quantity=decision.clip_quantity,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return eval_id

    async def save_override(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        risk_evaluation_id: UUID,
        authorised_by_user_id: UUID,
        reason_text: str,
        confirmation_chain: ConfirmationChain,
        state_snapshot_at_override: dict[str, Any],
        created_at: datetime,
    ) -> UUID:
        """INSERT a row into ``risk_overrides``; return the new id."""
        override_id = uuid.uuid4()
        row = RiskOverrideORM(
            id=override_id,
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            risk_evaluation_id=risk_evaluation_id,
            authorised_by_user_id=authorised_by_user_id,
            reason_text=reason_text,
            confirmation_chain=confirmation_chain.model_dump(mode="json"),
            state_snapshot_at_override=state_snapshot_at_override,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return override_id

    async def load_kill_switch_state(self, tenant_id: UUID) -> bool:
        """Return ``True`` iff the cached ``is_active`` row says so.

        Single-row indexed lookup — sub-millisecond on SQLite, ditto
        on PostgreSQL. This is the NFR-R5 hot-path read.
        """
        stmt = select(KillSwitchStateORM.is_active).where(
            KillSwitchStateORM.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        return bool(value) if value is not None else False

    async def append_kill_switch_event(
        self,
        *,
        tenant_id: UUID,
        transition: str,
        source: KillSwitchSource,
        actor_user_id: UUID | None,
        reason: str | None,
        created_at: datetime,
    ) -> UUID:
        """INSERT a row into ``kill_switch_events``; return the new id."""
        event_id = uuid.uuid4()
        row = KillSwitchEventORM(
            id=event_id,
            tenant_id=tenant_id,
            transition=transition,
            source=source,
            actor_user_id=actor_user_id,
            reason=reason,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return event_id

    async def update_kill_switch_cache(
        self,
        *,
        tenant_id: UUID,
        is_active: bool,
        last_event_id: UUID,
        updated_at: datetime,
    ) -> None:
        """Upsert the single cache row for ``tenant_id``.

        Uses SQLite's ``INSERT … ON CONFLICT DO UPDATE`` (Postgres has
        the same syntax). The ``kill_switch_state`` table is NOT
        flagged ``__tablename_is_append_only__``; UPDATE is permitted.

        On Postgres deployments (post-MVP) the same statement is
        valid — :func:`sqlalchemy.dialects.sqlite.insert` is the most
        portable form for the on_conflict_do_update pattern; the
        equivalent ``sqlalchemy.dialects.postgresql.insert`` lands as
        a follow-up when the engine is detected at boot.
        """
        stmt = sqlite_insert(KillSwitchStateORM).values(
            tenant_id=tenant_id,
            is_active=is_active,
            last_event_id=last_event_id,
            updated_at=updated_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id"],
            set_={
                "is_active": is_active,
                "last_event_id": last_event_id,
                "updated_at": updated_at,
            },
        )
        await self._session.execute(stmt)

    async def has_today_automatic_breach_event(
        self,
        tenant_id: UUID,
        today_utc: datetime,
        cap_type: CapType,
    ) -> bool:
        """True iff an ``automatic_cap_breach`` activation row exists for today.

        Used by the service-layer's first-breach-of-the-day guard so
        the kill-switch is auto-activated AT MOST once per day per
        tenant. ``cap_type`` is currently unused at the SQL level
        (we activate once per day across any cap type) but kept in
        the signature for forward-compat: a future refinement could
        scope to "first daily breach", "first weekly breach", etc.

        The ``DATE()`` SQL function works on both SQLite (DATE() built-
        in) and PostgreSQL.
        """
        # Cap type is reserved for future per-cap-type day buckets;
        # silence ruff about the unused arg without changing the API.
        _ = cap_type
        stmt = (
            select(func.count())
            .select_from(KillSwitchEventORM)
            .where(
                KillSwitchEventORM.tenant_id == tenant_id,
                KillSwitchEventORM.transition == "activated",
                KillSwitchEventORM.source == "automatic_cap_breach",
                func.date(KillSwitchEventORM.created_at) == func.date(today_utc),
            )
        )
        result = await self._session.execute(stmt)
        count = result.scalar_one()
        return bool(count and int(count) > 0)


# ---------------------------------------------------------------------------
# Helpers for service-layer commit sequencing.
# ---------------------------------------------------------------------------


async def commit_session(session: AsyncSession) -> None:
    """Wrapper for ``await session.commit()``.

    Kept here so the service layer's "two-write transaction" guarantee
    (per design D4) is grep-able from a single module. Repositories
    don't normally call commit themselves — the FastAPI ``get_db``
    dependency yields a session whose lifecycle is managed by the
    request scope; the service flushes + commits explicitly when it
    needs cross-table atomicity.
    """
    await session.commit()


async def execute_raw_sql(session: AsyncSession, sql: str) -> Any:
    """Escape hatch for tests that want to inspect rows via raw SQL.

    Not used by the service layer in production code paths.
    """
    return await session.execute(text(sql))


__all__ = ["RiskRepository", "commit_session", "execute_raw_sql"]
