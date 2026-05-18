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

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from iguanatrader.contexts.research.models import ResearchFact
    from iguanatrader.contexts.research.repository import ResearchRepository

logger = logging.getLogger(__name__)

_MARKER_RE = re.compile(
    r"\[fact:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]",
    re.IGNORECASE,
)

#: Maximum length of the human-readable value excerpt shipped to the
#: frontend. Long enough for "analyst_target_price · 164.50 USD" but
#: short enough to keep the citation chip compact.
_VALUE_EXCERPT_MAX = 60


@dataclass(frozen=True, slots=True)
class ResolvedCitation:
    """One resolved citation marker with full provenance for the frontend."""

    fact_id: UUID
    source_id: str
    source_url: str
    source_label: str
    retrieved_at: datetime
    retrieval_method: str
    fact_kind: str
    value_excerpt: str


def _summarise_fact_value(fact: ResearchFact) -> str:
    """Build a short, human-readable label of the fact's stored value.

    Used by :class:`ResolvedCitation.value_excerpt` so the frontend can
    render citation chips that say WHAT the fact is, not just where it
    came from. Truncates at :data:`_VALUE_EXCERPT_MAX` chars.

    Priority: numeric > text > JSON blob > empty string.
    """
    if fact.value_numeric is not None:
        suffix = ""
        if fact.currency:
            suffix = f" {fact.currency}"
        elif fact.unit:
            suffix = f" {fact.unit}"
        return _clip(f"{fact.value_numeric}{suffix}")
    if fact.value_text is not None:
        return _clip(fact.value_text)
    if fact.value_jsonb is not None:
        return _clip(_summarise_jsonb(fact.value_jsonb, fact_kind=fact.fact_kind))
    return ""


#: Per-fact-kind preferred scalar — when the multi-key payload contains
#: this key, surface its value as the chip excerpt instead of falling
#: back to "fact_kind only". Keeps chips concise yet meaningful for the
#: known shapes the OpenBB sidecar emits.
_FACT_KIND_PRIMARY_SCALAR: dict[str, tuple[str, ...]] = {
    "fundamentals": ("forward_pe", "pe_ratio", "price_to_book"),
    "analyst_ratings": ("analyst_target_price", "target_price"),
    "esg_score": ("esg_total", "total_score"),
}


def _summarise_jsonb(blob: Any, *, fact_kind: str = "") -> str:
    """Compact ``value_jsonb`` into a short scan-friendly excerpt.

    Behaviour:

    * ``{"value": X}`` (single-key) → ``str(X)``.
    * Multi-key dict with a known primary scalar for the fact_kind →
      ``"key=X"`` (e.g. ``forward_pe=32.74`` for fundamentals).
    * Other multi-key dicts → empty string. The chip falls back to
      ``fact_kind`` alone — meaningful, no garbage. Previous behaviour
      (a stringified ``{a, b, c, d}`` keys-only dump) leaked schema
      shape to the operator and read as broken UI.
    * Lists → ``[N items]``.
    * Scalars → ``str(value)``.
    """
    if isinstance(blob, dict):
        if len(blob) == 1:
            (only_value,) = blob.values()
            return str(only_value)
        for key in _FACT_KIND_PRIMARY_SCALAR.get(fact_kind, ()):
            if key in blob and blob[key] is not None:
                return f"{key}={blob[key]}"
        return ""
    if isinstance(blob, list):
        return f"[{len(blob)} items]"
    return json.dumps(blob, default=str)


def _clip(s: str) -> str:
    if len(s) <= _VALUE_EXCERPT_MAX:
        return s
    return s[: _VALUE_EXCERPT_MAX - 1] + "…"


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
                    fact_kind=fact.fact_kind,
                    value_excerpt=_summarise_fact_value(fact),
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
