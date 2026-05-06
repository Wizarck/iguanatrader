"""Audit trail service (slice R5 design D5).

Persists per-metric audit rows alongside the brief insert. One row per
``audit_trail_entry`` parsed from the LLM output's JSON block.

Idempotency: callers de-duplicate by ``(brief_id, metric)`` if retry-
safety is required. The append-only L2 trigger from migration ``0009``
blocks UPDATE/DELETE so re-runs against an existing brief_id raise
:class:`MissingProvenanceError`-style integrity errors at the boundary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from iguanatrader.contexts.research.models import ResearchAuditTrail
    from iguanatrader.contexts.research.repository import ResearchRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuditTrailEntry:
    """In-memory audit entry — one per computed metric in a brief.

    Mirrors the :class:`ResearchAuditTrail` ORM columns; the synthesizer
    parses one of these per JSON entry from the LLM's output.
    """

    metric: str
    formula: str
    inputs: list[dict[str, Any]]
    steps: list[dict[str, Any]] = field(default_factory=list)
    final_output: str = ""
    llm_call_id: UUID | None = None


class AuditTrailService:
    """Persists per-metric audit rows for a synthesised brief."""

    def __init__(self, repository: ResearchRepository) -> None:
        self._repo = repository

    async def persist(
        self,
        *,
        brief_id: UUID,
        brief_version: int,
        methodology: str,
        entries: list[AuditTrailEntry],
    ) -> list[ResearchAuditTrail]:
        """Insert one audit-trail row per entry. Returns ORM instances."""
        out: list[ResearchAuditTrail] = []
        for entry in entries:
            row = await self._repo.insert_audit_trail_entry(
                brief_id=brief_id,
                brief_version=brief_version,
                metric=entry.metric,
                formula=entry.formula,
                inputs=entry.inputs,
                steps=entry.steps,
                final_output=entry.final_output,
                methodology=methodology,
                llm_call_id=entry.llm_call_id,
            )
            out.append(row)
            logger.info(
                "research.audit_trail.persisted",
                extra={"brief_id": str(brief_id), "metric": entry.metric},
            )
        return out


__all__ = ["AuditTrailEntry", "AuditTrailService"]
