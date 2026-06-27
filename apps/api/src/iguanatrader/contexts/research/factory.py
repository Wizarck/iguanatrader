"""Shared :class:`BriefService` factory (slice ``brief-refresh-daemon-cron``).

Extracted verbatim from ``api/routes/research.py::_build_service`` so the
trading daemon's brief-refresh cron constructs the EXACT same wiring as the
REST route — env-gated Anthropic vs Fake LLM client + OpenBB/SEC-EDGAR
on-demand ingestion — without the daemon importing the API layer.

The daemon owns no HTTP request scope, so it (like the route) binds the
``ResearchRepository`` session via ``session_var`` before calling
:meth:`BriefService.refresh`; this factory only assembles the object graph.
"""

from __future__ import annotations

import os

import structlog

from iguanatrader.contexts.research.feature_provider import (
    CompositeFeatureProvider,
    TierAFeatureProvider,
    TierBFeatureProvider,
    TierCFeatureProvider,
)
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.contexts.research.service import BriefService
from iguanatrader.contexts.research.synthesis import (
    AuditTrailService,
    FakeLLMClient,
    Synthesizer,
)
from iguanatrader.contexts.research.synthesis.llm_client import LLMClient

log = structlog.get_logger("iguanatrader.contexts.research.factory")


def build_llm_client() -> LLMClient:
    """Pick the production or fake LLM client based on env.

    Production envs (``paper``/``live``/``production``) AND a populated
    ``ANTHROPIC_API_KEY`` → :class:`AnthropicLLMClient`; otherwise (dev/test
    or any unset key) → :class:`FakeLLMClient`. Mirrors the route factory so
    the daemon and the REST surface make byte-identical client decisions.
    """
    env = (os.environ.get("IGUANATRADER_ENV") or "").strip().lower()
    if env in {"paper", "live", "production"} and os.environ.get("ANTHROPIC_API_KEY"):
        from iguanatrader.contexts.research.synthesis.anthropic_client import (
            build_anthropic_llm_client_from_env,
        )

        return build_anthropic_llm_client_from_env()
    return FakeLLMClient()


def build_brief_service(
    repo: ResearchRepository,
    *,
    hindsight: object | None = None,
    bus: object | None = None,
) -> BriefService:
    """Compose :class:`BriefService` with its default dependency graph.

    On-demand ingestion (OpenBB sidecar + optional SEC EDGAR) is constructed
    lazily and degrades to ``None`` when the sidecar/UA is unavailable, so a
    brief refresh still synthesises from already-ingested facts. ``hindsight``
    (optional) enables FR81 narrative recall inside the brief; ``bus``
    (optional) lets the daemon publish ``ResearchBriefSynthesized`` so the
    subscribed ``HindsightRetainHandler`` retains the fresh thesis to the
    Hindsight bank (the historical-context loop the LLM gate reads back).
    """
    from iguanatrader.contexts.research.on_demand_ingestion import (
        EdgarSourceLike,
        OnDemandIngestionService,
    )
    from iguanatrader.contexts.research.sources.openbb_sidecar import (
        OpenBBSidecarSource,
    )

    composite = CompositeFeatureProvider(
        tier_a=TierAFeatureProvider(repo),
        tier_b=TierBFeatureProvider(repo),
        tier_c=TierCFeatureProvider(repo),
    )
    on_demand: OnDemandIngestionService | None
    try:
        openbb_source = OpenBBSidecarSource()
        edgar_source: EdgarSourceLike | None
        try:
            from iguanatrader.contexts.research.sources.sec_edgar import (
                SECEdgarSource,
            )

            edgar_source = SECEdgarSource()
        except Exception as edgar_exc:
            log.info("research.factory.edgar.unavailable", error=str(edgar_exc))
            edgar_source = None
        on_demand = OnDemandIngestionService(
            repository=repo,
            openbb_source=openbb_source,
            edgar_source=edgar_source,
        )
    except Exception as exc:  # pragma: no cover - defensive boot path
        log.warning("research.factory.on_demand_ingestion.unavailable", error=str(exc))
        on_demand = None

    return BriefService(
        repository=repo,
        composite_provider=composite,
        synthesizer=Synthesizer(llm_client=build_llm_client()),
        audit_service=AuditTrailService(repo),
        on_demand_ingestion=on_demand,
        hindsight=hindsight,
        bus=bus,  # type: ignore[arg-type]
    )
