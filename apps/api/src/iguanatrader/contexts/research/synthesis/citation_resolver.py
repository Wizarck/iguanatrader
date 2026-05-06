"""Citation resolver — parses ``[fact:<uuid>]`` markers (slice R5 D4).

Per design D4 + j3.md §9 (locked 2026-05-05): citation marker syntax is
``[fact:<uuid>]`` with the canonical UUID v4 dash format. Regex is
case-insensitive (LLMs sometimes uppercase hex).

The resolver:

1. Parses the brief body for all marker matches.
2. Batch-fetches matching ``research_facts`` rows via repository.
3. Returns ``(citations, broken_markers)`` — citations resolve to a
   :class:`ResolvedCitation` with the bind-the-frontend-needs surface;
   broken markers are surfaced (not silently dropped) and logged via
   ``research.citation.broken`` structlog event.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from iguanatrader.contexts.research.repository import ResearchRepository

logger = logging.getLogger(__name__)

_MARKER_RE = re.compile(
    r"\[fact:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ResolvedCitation:
    """One resolved citation marker with full provenance for the frontend."""

    fact_id: UUID
    source_id: str
    source_url: str
    source_label: str
    retrieved_at: datetime
    retrieval_method: str


class CitationResolver:
    """Sync citation marker → research_facts resolver."""

    def __init__(self, repository: ResearchRepository) -> None:
        self._repo = repository

    @staticmethod
    def parse_markers(body: str) -> list[UUID]:
        """Return all UUIDs referenced by ``[fact:<uuid>]`` markers."""
        out: list[UUID] = []
        seen: set[UUID] = set()
        for match in _MARKER_RE.finditer(body):
            try:
                fact_id = UUID(match.group(1))
            except ValueError:
                continue
            if fact_id in seen:
                continue
            seen.add(fact_id)
            out.append(fact_id)
        return out

    async def resolve(
        self,
        body: str,
    ) -> tuple[list[ResolvedCitation], list[str]]:
        """Resolve all markers in ``body`` against repository.

        Returns ``(resolved, broken)`` — ``resolved`` is the list of
        :class:`ResolvedCitation` (one per unique UUID); ``broken`` is the
        list of marker UUIDs that did not resolve to a fact (cross-tenant
        or invented).
        """
        marker_ids = self.parse_markers(body)
        if not marker_ids:
            return [], []

        facts = await self._repo.facts_by_ids(marker_ids)
        resolved: list[ResolvedCitation] = []
        broken: list[str] = []
        for fact_id in marker_ids:
            fact = facts.get(fact_id)
            if fact is None:
                broken.append(str(fact_id))
                logger.warning(
                    "research.citation.broken",
                    extra={"fact_id": str(fact_id)},
                )
                continue
            resolved.append(
                ResolvedCitation(
                    fact_id=fact_id,
                    source_id=fact.source_id,
                    source_url=fact.source_url,
                    source_label=fact.source_id,
                    retrieved_at=fact.retrieved_at,
                    retrieval_method=fact.retrieval_method,
                )
            )
        return resolved, broken

    @staticmethod
    def validate_against_bundle(
        body: str,
        allowed_fact_ids: set[UUID],
    ) -> list[UUID]:
        """Return marker UUIDs in ``body`` that are NOT in ``allowed_fact_ids``.

        Used by the synthesizer as a pre-persist gate: any invented UUID
        triggers :class:`InvalidCitationError` and aborts the synthesis.
        """
        marker_ids = CitationResolver.parse_markers(body)
        return [m for m in marker_ids if m not in allowed_fact_ids]


__all__ = [
    "CitationResolver",
    "ResolvedCitation",
]
