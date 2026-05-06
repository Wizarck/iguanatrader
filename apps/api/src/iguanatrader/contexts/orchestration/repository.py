"""Repository for ``routine_runs`` + ``alert_events`` (slice O2)."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.contexts.orchestration.errors import DuplicateRoutineTriggerError
from iguanatrader.shared.kernel import BaseRepository

logger = logging.getLogger(__name__)


class OrchestrationRepository(BaseRepository):
    """Sync repository for routine_runs + alert_events."""

    @property
    def _session(self) -> AsyncSession:
        """Narrow ``BaseRepository.session: Any`` → :class:`AsyncSession`.

        Mirrors :class:`ResearchRepository._session` pattern so mypy
        --strict catches misuse at the repository boundary.
        """
        sess: Any = self.session
        return sess  # type: ignore[no-any-return]

    async def insert_routine_run(
        self,
        *,
        routine_name: str,
        scheduled_at: datetime,
        started_at: datetime,
        status: str,
    ) -> UUID:
        """Insert a new ``routine_runs`` row. Raises
        :class:`DuplicateRoutineTriggerError` on the unique-index race.
        """
        run_id = uuid4()
        try:
            await self._session.execute(
                sa.text(
                    "INSERT INTO routine_runs "
                    "(id, tenant_id, routine_name, scheduled_at, "
                    "started_at, status, created_at) "
                    "VALUES (:id, :tid, :name, :sched, :started, :status, :created)"
                ),
                {
                    "id": str(run_id),
                    "tid": self._tenant_id_str(),
                    "name": routine_name,
                    "sched": scheduled_at,
                    "started": started_at,
                    "status": status,
                    "created": started_at,
                },
            )
        except IntegrityError as exc:
            raise DuplicateRoutineTriggerError(
                detail=(
                    f"routine {routine_name!r} already has a row for "
                    f"scheduled_at={scheduled_at.isoformat()}"
                ),
            ) from exc
        return run_id

    async def update_routine_run(
        self,
        *,
        run_id: UUID,
        status: str,
        ended_at: datetime,
        duration_ms: int,
        digest_payload: dict[str, Any],
        cost_usd: Decimal | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update a routine_runs row to a terminal status."""
        import json

        await self._session.execute(
            sa.text(
                "UPDATE routine_runs SET "
                "status = :status, "
                "ended_at = :ended, "
                "duration_ms = :duration_ms, "
                "digest_payload = :digest, "
                "cost_usd = :cost_usd, "
                "error_message = :error_message "
                "WHERE id = :id"
            ),
            {
                "status": status,
                "ended": ended_at,
                "duration_ms": duration_ms,
                "digest": json.dumps(digest_payload),
                "cost_usd": cost_usd,
                "error_message": error_message,
                "id": str(run_id),
            },
        )

    async def insert_alert_event(
        self,
        *,
        event_name: str,
        tier: int,
        routing_decision: str,
        payload: dict[str, Any],
        correlation_id: UUID | None = None,
    ) -> UUID:
        """Insert one ``alert_events`` row. Append-only via slice-3 listener."""
        import json

        alert_id = uuid4()
        await self._session.execute(
            sa.text(
                "INSERT INTO alert_events "
                "(id, tenant_id, event_name, tier, routing_decision, "
                "payload, correlation_id, created_at) "
                "VALUES (:id, :tid, :event, :tier, :routing, :payload, "
                ":corr, CURRENT_TIMESTAMP)"
            ),
            {
                "id": str(alert_id),
                "tid": self._tenant_id_str(),
                "event": event_name,
                "tier": tier,
                "routing": routing_decision,
                "payload": json.dumps(payload),
                "corr": str(correlation_id) if correlation_id else None,
            },
        )
        return alert_id

    def _tenant_id_str(self) -> str:
        from iguanatrader.shared.contextvars import tenant_id_var

        tid = tenant_id_var.get()
        return str(tid) if tid is not None else ""


__all__ = ["OrchestrationRepository"]
