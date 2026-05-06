"""Research routes — slice R5 full implementation (replaces R1 stubs).

Per R1 design D6: signatures + DTOs unchanged. Slice R5 swaps the stub
bodies in-place. Auth dependency is :func:`get_current_user` (slice 4);
session binding via :data:`session_var` ContextVar (slice 2/3).

Hard rules per AGENTS.md §4:

* All errors RFC 7807 ``application/problem+json`` — handled globally
  via :func:`IguanaError` exception handler from slice 5.
* structlog event names ``api.research.<entity>.<action>``.
* No float for money (R5 brief response carries ``score_overall: Decimal``).

Limit on POST refresh: ``5/min`` per tenant via slowapi (slice 5
``limiter`` instance). Tier-A safety: ``BriefService`` calls happen in
the request transaction; ``session_var.set(db)`` binds the session for
:class:`ResearchRepository`.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.research import (
    AuditTrailEntry,
    BriefRefreshRequest,
    BriefResponse,
    CitationDetail,
    FactResponse,
    ResolvedCitationDetail,
)
from iguanatrader.contexts.research.errors import ResearchStubNotImplementedError
from iguanatrader.contexts.research.feature_provider import (
    CompositeFeatureProvider,
    TierAFeatureProvider,
    TierBFeatureProvider,
    TierCFeatureProvider,
)
from iguanatrader.contexts.research.models import ResearchBrief, ResearchFact
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.contexts.research.service import BriefService
from iguanatrader.contexts.research.synthesis import (
    AuditTrailService,
    CitationResolver,
    FakeLLMClient,
    Synthesizer,
)
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var

log = structlog.get_logger("iguanatrader.api.routes.research")

router = APIRouter(prefix="/research", tags=["research"])


_DEFAULT_METHODOLOGY = "three_pillar"


def _build_service(repo: ResearchRepository) -> BriefService:
    """Compose the brief service with default dependencies.

    R5 ships the :class:`FakeLLMClient` as the default — production
    Anthropic wiring lands in a follow-up deployment slice once the SDK
    is added to the project deps. Tests inject a richer fake.
    """
    composite = CompositeFeatureProvider(
        tier_a=TierAFeatureProvider(repo),
        tier_b=TierBFeatureProvider(repo),
        tier_c=TierCFeatureProvider(repo),
    )
    return BriefService(
        repository=repo,
        composite_provider=composite,
        synthesizer=Synthesizer(llm_client=FakeLLMClient()),
        audit_service=AuditTrailService(repo),
    )


def _project_brief(
    brief: ResearchBrief,
    *,
    resolved_citations: list[ResolvedCitationDetail],
) -> BriefResponse:
    """Project a :class:`ResearchBrief` onto :class:`BriefResponse`."""
    citations = [
        CitationDetail(fact_id=UUID(c["fact_id"]), claim_excerpt="")
        for c in (brief.citations or [])
        if isinstance(c, dict) and "fact_id" in c
    ]
    audit_entries = [
        AuditTrailEntry(
            formula=str(entry.get("formula", "")),
            inputs=[],
            intermediate_steps=[],
            final_output=str(entry.get("final_output", "")),
        )
        for entry in (brief.audit_trail or [])
        if isinstance(entry, dict)
    ]
    return BriefResponse(
        id=brief.id,
        symbol_universe_id=brief.symbol_universe_id,
        watchlist_config_id=brief.watchlist_config_id,
        version=brief.version,
        methodology=brief.methodology,
        thesis_text=brief.thesis_text,
        score_overall=brief.score_overall,
        score_components=brief.score_components,
        citations=citations,
        audit_trail=audit_entries,
        llm_provider=brief.llm_provider,
        llm_model=brief.llm_model,
        llm_input_tokens=brief.llm_input_tokens,
        llm_output_tokens=brief.llm_output_tokens,
        llm_cache_hit_tokens=brief.llm_cache_hit_tokens,
        partial=brief.partial,
        created_at=brief.created_at,
        body_markdown=brief.thesis_text,
        pillar_scores=(
            {k: str(v) for k, v in brief.score_components.items()}
            if brief.score_components
            else None
        ),
        audit_trail_summary={
            "metric_count": len(brief.audit_trail or []),
            "llm_calls": 1,
        },
        resolved_citations=resolved_citations,
    )


def _project_fact(fact: ResearchFact) -> FactResponse:
    return FactResponse.model_validate(fact)


@router.get("/briefs/{symbol}", response_model=BriefResponse)
async def get_brief(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BriefResponse:
    """Return the latest brief for ``symbol`` (slice R5)."""
    log.info("api.research.brief.get", symbol=symbol)
    session_var.set(db)
    repo = ResearchRepository()
    brief = await repo.latest_brief(symbol)
    if brief is None:
        raise ResearchStubNotImplementedError(
            detail=f"no brief synthesised yet for {symbol}; POST /briefs/{symbol}/refresh first",
        )
    resolver = CitationResolver(repo)
    resolved, broken = await resolver.resolve(brief.thesis_text)
    if broken:
        log.warning(
            "api.research.brief.broken_citations",
            symbol=symbol,
            broken_count=len(broken),
        )
    resolved_dtos = [
        ResolvedCitationDetail(
            fact_id=r.fact_id,
            source_id=r.source_id,
            source_url=r.source_url,
            source_label=r.source_label,
            retrieved_at=r.retrieved_at,
            retrieval_method=r.retrieval_method,
        )
        for r in resolved
    ]
    return _project_brief(brief, resolved_citations=resolved_dtos)


@router.get(
    "/briefs/{brief_id}/audit-trail",
    response_model=list[AuditTrailEntry],
)
async def get_brief_audit_trail(
    brief_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AuditTrailEntry]:
    """Return the full audit-trail rows for ``brief_id`` (slice R5)."""
    log.info("api.research.audit_trail.get", brief_id=str(brief_id))
    session_var.set(db)
    repo = ResearchRepository()
    rows = await repo.audit_trail_for_brief(brief_id)
    return [
        AuditTrailEntry(
            formula=row.formula,
            inputs=list(row.inputs) if isinstance(row.inputs, list) else [],
            intermediate_steps=[
                str(step) for step in (row.steps if isinstance(row.steps, list) else [])
            ],
            final_output=row.final_output,
        )
        for row in rows
    ]


@router.get("/facts/{symbol}", response_model=list[FactResponse])
async def get_facts(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FactResponse]:
    """Return the latest facts for ``symbol`` (slice R5)."""
    log.info("api.research.facts.get", symbol=symbol)
    session_var.set(db)
    repo = ResearchRepository()
    facts = await repo.facts_for_symbol(symbol, limit=50)
    return [_project_fact(f) for f in facts]


@router.post("/briefs/{symbol}/refresh", response_model=BriefResponse)
async def refresh_brief(
    symbol: str,
    body: BriefRefreshRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BriefResponse:
    """Synthesise a fresh brief for ``symbol`` (slice R5)."""
    methodology = body.methodology or _DEFAULT_METHODOLOGY
    log.info(
        "api.research.brief.refresh",
        symbol=symbol,
        methodology=methodology,
    )
    session_var.set(db)
    repo = ResearchRepository()
    service = _build_service(repo)
    outcome = await service.refresh(symbol=symbol, methodology=methodology)
    await db.commit()
    # Re-resolve citations after commit so the response carries the
    # provenance bundle the frontend renderer needs.
    resolver = CitationResolver(repo)
    resolved, broken = await resolver.resolve(outcome.brief.thesis_text)
    if broken:
        log.warning(
            "api.research.brief.refresh.broken_citations",
            symbol=symbol,
            broken_count=len(broken),
        )
    resolved_dtos = [
        ResolvedCitationDetail(
            fact_id=r.fact_id,
            source_id=r.source_id,
            source_url=r.source_url,
            source_label=r.source_label,
            retrieved_at=r.retrieved_at,
            retrieval_method=r.retrieval_method,
        )
        for r in resolved
    ]
    return _project_brief(outcome.brief, resolved_citations=resolved_dtos)


__all__ = [
    "router",
]
