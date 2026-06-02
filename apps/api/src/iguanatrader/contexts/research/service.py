"""Brief service — orchestrates synthesis + persist (slice R5 design D3 + D5).

``BriefService.refresh()`` runs the 7-step pipeline + retry-on-version-
collision per R1 design D5. Failure modes per design D10:

* :class:`LLMUnavailableError` (would be raised by real Anthropic client) →
  the service catches via the LLMClient Protocol and returns the latest
  brief with a ``stale=True`` indication. (FakeLLMClient does not raise.)
* :class:`BudgetExceededError` (O1 budget gate) → re-raised; route layer
  surfaces 402.
* :class:`InvalidCitationError` → re-raised; synthesis aborts.
* :class:`BriefSynthesisShortError` → re-raised; synthesis aborts.

The service is constructed by the route handler with explicit
dependencies (repository + synthesizer + composite_provider + llm_routing
helper). Tests inject fakes for each.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from iguanatrader.contexts.research.feature_provider import (
    CompositeFeatureProvider,
)
from iguanatrader.contexts.research.methodology import METHODOLOGY_REGISTRY
from iguanatrader.contexts.research.synthesis import (
    AuditTrailService,
    Synthesizer,
)
from iguanatrader.shared.messagebus import MessageBus
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from iguanatrader.contexts.research.models import (
        ResearchAuditTrail,
        ResearchBrief,
        ResearchFact,
    )
    from iguanatrader.contexts.research.repository import ResearchRepository

logger = logging.getLogger(__name__)


MAX_INSERT_RETRIES = 3
LLM_PROVIDER = "anthropic"  # Production wiring lands in deployment slice.


@dataclass(frozen=True, slots=True)
class BriefRefreshOutcome:
    """Service-level result wrapping the persisted brief + audit rows."""

    brief: ResearchBrief
    audit_rows: list[ResearchAuditTrail]
    stale: bool = False


class BriefService:
    """Orchestrates feature → methodology → LLM → persist."""

    def __init__(
        self,
        *,
        repository: ResearchRepository,
        composite_provider: CompositeFeatureProvider,
        synthesizer: Synthesizer,
        audit_service: AuditTrailService,
        bus: MessageBus | None = None,
        default_model: str = "claude-sonnet-4-6",
        hindsight: Any | None = None,
        on_demand_ingestion: Any | None = None,
    ) -> None:
        self._repo = repository
        self._provider = composite_provider
        self._synth = synthesizer
        self._audit = audit_service
        self._bus = bus
        self._default_model = default_model
        # Slice R6: optional Hindsight Port for FR81 narrative recall.
        # When None or feature flag OFF, refresh() skips the recall path
        # transparently. Test-existing callers leave this as None.
        self._hindsight = hindsight
        # Slice research-ad-hoc-mode: optional ingestion service that
        # populates research_facts inline when refresh is called for a
        # brand-new symbol. When None, refresh keeps the legacy
        # behaviour (requires the symbol pre-registered + facts already
        # in DB). Production wiring lives in the route handler.
        self._ingestion = on_demand_ingestion

    async def refresh(
        self,
        symbol: str,
        methodology: str,
    ) -> BriefRefreshOutcome:
        """Run synthesis + persist a new brief version.

        Slice ``research-refresh-always-reingest`` evolved the pipeline:

        1. Resolve / auto-register symbol_universe + watchlist_config.
        2. ALWAYS fetch facts from configured ingestion sources (no
           longer gated on ``newly_registered``). Idempotent at the
           ``dedupe_key`` partial unique index — duplicate inserts are
           silently rolled back via SAVEPOINT in
           :meth:`OnDemandIngestionService._persist`, so re-running is
           safe and cheap.
        3. Feature provider reads from research_facts.
        4. Methodology scoring + LLM synthesis + persist.
        """
        if methodology not in METHODOLOGY_REGISTRY:
            raise ValueError(
                f"unknown methodology {methodology!r}; "
                f"expected one of {sorted(METHODOLOGY_REGISTRY)}"
            )

        symbol_universe_id, watchlist_config_id, _ = await self._resolve_or_register_fks(symbol)
        # Slice ``research-refresh-always-reingest``: previously this
        # path only fired when ``newly_registered`` was True, so any
        # symbol whose first ingestion was partial (EDGAR outage,
        # missing tier-A revenue tag, sidecar timeout) stayed partial
        # forever — subsequent refresh requests skipped ingestion
        # entirely. Per-fact idempotency at ``dedupe_key`` (partial
        # unique index from migration 0008 + SAVEPOINT-per-insert in
        # ``OnDemandIngestionService._persist``) makes re-runs safe and
        # cheap: existing rows are silently skipped, only fresh facts
        # land. Cost: an extra sidecar/EDGAR round-trip per refresh,
        # bounded by the rate limiters in the adapter ladder.
        if self._ingestion is not None:
            try:
                await self._ingestion.ingest(
                    symbol=symbol,
                    symbol_universe_id=symbol_universe_id,
                )
            except Exception as exc:
                # Ingestion failure is non-fatal: brief synthesis can
                # still proceed and will simply emit partial=True with
                # null pillars. The operator sees the empty result and
                # can retry, but we don't 5xx the route on a flaky
                # upstream.
                logger.warning(
                    "research.brief.on_demand_ingestion_failed",
                    extra={"symbol": symbol, "error": str(exc)},
                )

        feature_bundle = await self._provider.fetch(
            symbol=symbol,
            methodology=methodology,
            since=utc_now(),
        )

        close_pair = feature_bundle.values.get("close_price")
        if not close_pair or close_pair[0] is None:
            from iguanatrader.contexts.research.errors import InsufficientPriceDataError

            raise InsufficientPriceDataError(
                detail=(
                    f"close_price missing for {symbol}; " f"ingest price bars before synthesis"
                ),
            )

        score_fn = METHODOLOGY_REGISTRY[methodology]
        methodology_result = score_fn(feature_bundle.values_only())

        # Slice R6 - FR81 gated narrative recall via Hindsight.
        narrative_context = await self._maybe_recall_hindsight(symbol)

        synthesised = await self._synth.synthesize(
            symbol=symbol,
            methodology=methodology,
            feature_bundle=feature_bundle,
            methodology_result=methodology_result,
            model=self._default_model,
            narrative_context=narrative_context,
        )

        # symbol_universe_id + watchlist_config_id already resolved at
        # the top of the method (slice research-ad-hoc-mode). Locals
        # remain in scope for the persist block below.
        attempt = 0
        last_exc: Exception | None = None
        while attempt < MAX_INSERT_RETRIES:
            attempt += 1
            next_version = await self._next_version(symbol_universe_id=symbol_universe_id)
            try:
                brief = await self._repo.insert_brief(
                    symbol_universe_id=symbol_universe_id,
                    watchlist_config_id=watchlist_config_id,
                    version=next_version,
                    methodology=methodology,
                    thesis_text=synthesised.body_markdown,
                    score_overall=Decimal(str(synthesised.overall_score)),
                    score_components={
                        name: str(score) for name, score in synthesised.pillars.items()
                    },
                    citations=[{"fact_id": str(fid)} for fid in synthesised.citations_used],
                    audit_trail=[
                        {
                            "metric": e.metric,
                            "formula": e.formula,
                            "final_output": e.final_output,
                        }
                        for e in synthesised.audit_entries
                    ],
                    llm_provider=LLM_PROVIDER,
                    llm_model=synthesised.llm_completion.model,
                    llm_input_tokens=synthesised.llm_completion.tokens_input,
                    llm_output_tokens=synthesised.llm_completion.tokens_output,
                    llm_cache_hit_tokens=(
                        synthesised.llm_completion.tokens_input
                        if synthesised.llm_completion.cached
                        else 0
                    ),
                    partial=synthesised.partial,
                )
                break
            except IntegrityError as exc:
                last_exc = exc
                logger.info(
                    "research.brief.version_collision",
                    extra={"attempt": attempt, "next_version": next_version},
                )
                continue
        else:
            raise RuntimeError(
                f"brief insert failed after {MAX_INSERT_RETRIES} retries: {last_exc}"
            )

        audit_rows = await self._audit.persist(
            brief_id=brief.id,
            brief_version=brief.version,
            methodology=methodology,
            entries=synthesised.audit_entries,
        )

        if self._bus is not None:
            from iguanatrader.contexts.research.events import ResearchBriefSynthesized

            await self._bus.publish(
                ResearchBriefSynthesized(
                    brief_id=brief.id,
                    symbol_universe_id=brief.symbol_universe_id,
                    version=brief.version,
                    methodology=methodology,
                    partial=brief.partial,
                )
            )

        logger.info(
            "research.brief.synthesised",
            extra={
                "symbol": symbol,
                "methodology": methodology,
                "version": brief.version,
                "partial": brief.partial,
            },
        )
        return BriefRefreshOutcome(brief=brief, audit_rows=audit_rows)

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------

    async def get_brief(self, symbol: str) -> ResearchBrief | None:
        return await self._repo.latest_brief(symbol)

    async def facts(self, symbol: str, *, limit: int = 50) -> list[ResearchFact]:
        return await self._repo.facts_for_symbol(symbol, limit=limit)

    async def audit_trail(self, brief_id: UUID) -> list[ResearchAuditTrail]:
        return await self._repo.audit_trail_for_brief(brief_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _maybe_recall_hindsight(self, symbol: str) -> list[str]:
        """Slice R6 - FR81 gated narrative recall.

        Returns ``[]`` (no-op) when:

        * ``self._hindsight is None`` (R5 archive callers / tests).
        * ``tenant.feature_flags.hindsight_recall_enabled`` is falsy.
        * Recall raises (timeout / unavailable) - logs + degrades.

        Returns the recall result list otherwise.
        """
        if self._hindsight is None:
            return []
        from iguanatrader.contexts.research.hindsight import (
            HindsightTimeout,
            HindsightUnavailable,
        )
        from iguanatrader.persistence import Tenant
        from iguanatrader.shared.contextvars import tenant_id_var

        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            return []
        try:
            tenant = await self._repo._session.get(Tenant, tenant_id)
        except Exception as exc:
            logger.warning(
                "research.hindsight.tenant_lookup_failed",
                extra={"symbol": symbol, "error": str(exc)},
            )
            return []
        if tenant is None:
            return []
        flags = getattr(tenant, "feature_flags", {}) or {}
        if not bool(flags.get("hindsight_recall_enabled", False)):
            return []
        bank = f"iguanatrader-research-{tenant_id}"
        query = f"{symbol} fundamentals macro context lessons"
        try:
            result = await self._hindsight.recall(
                bank=bank,
                query=query,
                limit=20,
                timeout_ms=2000,
            )
            return [str(item) for item in result]
        except (HindsightUnavailable, HindsightTimeout) as exc:
            logger.warning(
                "research.hindsight.recall_failed",
                extra={"symbol": symbol, "error": str(exc)},
            )
            return []
        except Exception as exc:
            logger.warning(
                "research.hindsight.recall_unexpected_error",
                extra={"symbol": symbol, "error": str(exc)},
            )
            return []

    async def _resolve_or_register_fks(
        self,
        symbol: str,
    ) -> tuple[UUID, UUID, bool]:
        """Return ``(symbol_universe_id, watchlist_config_id, newly_registered)``.

        Slice research-ad-hoc-mode: if the symbol is not yet in the
        tenant's universe, auto-create the rows with the
        :mod:`registration` module's defaults (tier=primary,
        schedule=manual). The third tuple element distinguishes the
        first-time path (caller may want to trigger inline ingestion)
        from the steady-state path (rows already existed).
        """
        from iguanatrader.contexts.research.registration import (
            ensure_symbol_registered,
        )
        from iguanatrader.shared.contextvars import tenant_id_var

        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            raise RuntimeError(
                "BriefService.refresh requires tenant_id_var to be set; "
                "request middleware should populate it before invoking the route."
            )

        outcome = await ensure_symbol_registered(
            session=self._repo._session,
            tenant_id=tenant_id,
            symbol=symbol,
        )
        return (
            outcome.symbol_universe_id,
            outcome.watchlist_config_id,
            outcome.created,
        )

    async def _next_version(self, *, symbol_universe_id: UUID) -> int:
        """Compute next monotonic version for ``(tenant, symbol_universe)``.

        Per R1 design D5: ``MAX(version) + 1`` per tenant + symbol; the
        unique-index race is handled by the retry loop in :meth:`refresh`.
        """
        from iguanatrader.contexts.research.models import ResearchBrief

        session = self._repo._session
        stmt = sa.select(sa.func.max(ResearchBrief.version)).where(
            ResearchBrief.symbol_universe_id == symbol_universe_id
        )
        result = await session.execute(stmt)
        current_max = result.scalar() or 0
        return int(current_max) + 1


__all__ = ["BriefRefreshOutcome", "BriefService"]
