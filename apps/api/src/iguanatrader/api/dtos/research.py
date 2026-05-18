"""Pydantic v2 DTOs for the research API surface.

Per design D6 + R5 forward compatibility:

* :class:`FactResponse` — projection of :class:`ResearchFact` for API
  consumers. Excludes the raw payload columns (consumers query the audit
  endpoint to reconstruct the chain).
* :class:`BriefResponse` — projection of :class:`ResearchBrief` including
  the citation chain + audit trail (FR70 + NFR-O8).
* :class:`CitationDetail` — array element shape inside ``citations``.
* :class:`AuditTrailEntry` — array element shape inside ``audit_trail``.
* :class:`BriefRefreshRequest` — empty body for ``POST .../refresh``;
  declared so the OpenAPI schema lists the endpoint as accepting JSON.

R5 (``research-brief-synthesis``) consumes these unchanged. The
typegen pipeline regenerates ``packages/shared-types/src/index.ts``
once R1 lands; the SvelteKit frontend can wire the typed client even
though every endpoint returns 501 until R5 ships.

All datetimes serialise as ISO 8601 UTC (Pydantic v2 default for
:class:`datetime`); per project memory ``ISO 8601 single date format``,
this is the only timestamp form anywhere in iguanatrader.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CitationDetail(BaseModel):
    """One entry inside :attr:`BriefResponse.citations`.

    Per FR70 + NFR-O8: every numeric or factual claim in a brief MUST
    cite the originating :class:`ResearchFact` row. The ``claim_excerpt``
    is the short text fragment from the brief that this citation backs.
    R5 enforces "no orphan citations" + "no missing fact_id" at brief
    insert time.
    """

    model_config = ConfigDict(extra="forbid")

    fact_id: UUID
    claim_excerpt: str


class AuditTrailEntry(BaseModel):
    """One entry inside :attr:`BriefResponse.audit_trail`.

    Per FR70: every numeric output in a brief is reproducible from
    the recorded ``formula`` + ``inputs`` + ``intermediate_steps`` +
    ``final_output``. R5's audit-trail renderer iterates this list to
    show the user the exact derivation chain.

    ``inputs`` is a list of ``{fact_id, value}`` dicts; declared as
    ``list[dict[str, Any]]`` to leave the per-input shape flexible for
    the various calculation kinds (numeric ratio, sentiment aggregate,
    weighted score, etc.). ``final_output`` is ``str | float`` because
    some calculations produce labels (e.g. ``"Buy"``) rather than
    numerics.
    """

    model_config = ConfigDict(extra="forbid")

    formula: str
    inputs: list[dict[str, Any]]
    intermediate_steps: list[str]
    final_output: str | float


class FactResponse(BaseModel):
    """API projection of :class:`ResearchFact`.

    Mirrors the columns that are safe to expose to API consumers. Excludes
    the raw payload (consumers query the audit-trail endpoint to
    reconstruct provenance). Decimal values serialise as strings to
    preserve precision through JSON.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    source_id: str
    symbol_universe_id: UUID | None
    fact_kind: str
    value_numeric: Decimal | None
    value_text: str | None
    value_jsonb: Any | None
    unit: str | None
    currency: str | None
    effective_from: datetime
    effective_to: datetime | None
    recorded_from: datetime
    recorded_to: datetime | None
    source_url: str
    retrieval_method: str
    retrieved_at: datetime
    confidence: Decimal | None
    created_at: datetime


class ResolvedCitationDetail(BaseModel):
    """Slice R5 — citation enriched with the resolved fact's provenance.

    Returned alongside :class:`BriefResponse` so the frontend renderer can
    paint ``[fact:<uuid>]`` markers as clickable :class:`CitationLink`
    components without an extra round-trip.

    Slice ``citation-chip-enrichment`` (2026-05-18) adds ``fact_kind`` +
    ``value_excerpt`` so chips can display WHAT the fact says, not just
    where it came from — particularly important for facts whose
    ``source_url`` is an internal compose-network URL (e.g. OpenBB
    sidecar) that the browser can't reach.
    """

    model_config = ConfigDict(extra="forbid")

    fact_id: UUID
    source_id: str
    source_url: str
    source_label: str
    retrieved_at: datetime
    retrieval_method: str
    fact_kind: str = ""
    value_excerpt: str = ""


class BriefResponse(BaseModel):
    """API projection of :class:`ResearchBrief` with citations + audit trail.

    Per FR70 + FR73: the response is the canonical "show your work"
    payload. Citations + audit_trail are required (NOT NULL on the model
    side; the empty list is allowed but the field MUST be present). R5
    populates these from its synthesis pipeline; R1 lands the schema so
    the OpenAPI surface is stable across the Wave 3 fan-out.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    symbol_universe_id: UUID
    watchlist_config_id: UUID
    version: int
    methodology: str
    thesis_text: str
    score_overall: Decimal | None
    score_components: dict[str, Any] | None
    citations: list[CitationDetail] = Field(default_factory=list)
    audit_trail: list[AuditTrailEntry] = Field(default_factory=list)
    llm_provider: str
    llm_model: str
    llm_input_tokens: int
    llm_output_tokens: int
    llm_cache_hit_tokens: int
    partial: bool
    created_at: datetime
    # Slice R5 (research-brief-synthesis) — additive fields. Old clients
    # consuming the R1 shape ignore these gracefully (Pydantic ``extra="forbid"``
    # but typegen now ships these in shared-types so the frontend is updated).
    body_markdown: str | None = None
    pillar_scores: dict[str, str] | None = None
    audit_trail_summary: dict[str, int] | None = None
    next_scheduled_refresh_at: datetime | None = None
    last_fact_recorded_at: datetime | None = None
    stale: bool = False
    resolved_citations: list[ResolvedCitationDetail] = Field(default_factory=list)


class BriefStatsResponse(BaseModel):
    """Snapshot KPIs for the brief detail page (slice research-stat-block).

    Computed live from the latest ingested facts — independent of brief
    synthesis, so the stat block updates whenever the operator hits
    refresh on the page without re-incurring LLM cost.

    Every field is Optional: a brand-new ad-hoc symbol with only the
    OpenBB endpoints completed will populate the price + valuation
    blocks; benchmark-dependent fields (beta, relative strength) need
    SPY's historical_prices_window to be ingested separately.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str
    as_of: str | None

    last_price: float | None
    day_change_pct: float | None
    high_52w: float | None
    low_52w: float | None
    position_in_52w_pct: float | None
    avg_volume_20d: float | None

    volatility_20d_annualized: float | None
    beta_vs_spy_60d: float | None

    forward_pe: float | None
    pe_ratio: float | None
    price_to_book: float | None
    market_cap: float | None

    rsi_14: float | None
    sma_50: float | None
    sma_200: float | None
    pos_vs_sma_50_pct: float | None
    pos_vs_sma_200_pct: float | None
    return_3m_pct: float | None
    return_12m_pct: float | None
    relative_strength_vs_spy_3m_pct: float | None
    relative_strength_vs_spy_12m_pct: float | None

    analyst_target_price: float | None
    analyst_count: int | None
    upside_to_target_pct: float | None


class BriefRefreshRequest(BaseModel):
    """Request body for ``POST /api/v1/research/briefs/{symbol}/refresh``.

    R5 adds an optional ``methodology`` override; default ``None`` falls
    back to the watchlist's configured methodology. The OpenAPI schema
    accepts an empty JSON body for backwards compatibility with R1's
    contract.
    """

    model_config = ConfigDict(extra="forbid")
    methodology: str | None = None


class BriefRefreshProgressEvent(BaseModel):
    """SSE payload for ``research.brief.refresh.progress`` (slice R5 D8)."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    step: str
    percent: int
    brief_version_in_flight: int | None = None


__all__ = [
    "AuditTrailEntry",
    "BriefRefreshProgressEvent",
    "BriefRefreshRequest",
    "BriefResponse",
    "CitationDetail",
    "FactResponse",
    "ResolvedCitationDetail",
]
