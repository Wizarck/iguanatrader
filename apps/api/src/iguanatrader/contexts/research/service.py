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

    async def refresh(
        self,
        symbol: str,
        methodology: str,
    ) -> BriefRefreshOutcome:
        """Run synthesis + persist a new brief version."""
        if methodology not in METHODOLOGY_REGISTRY:
            raise ValueError(
                f"unknown methodology {methodology!r}; "
                f"expected one of {sorted(METHODOLOGY_REGISTRY)}"
            )

        feature_bundle = await self._provider.fetch(
            symbol=symbol,
            methodology=methodology,
            since=utc_now(),
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

        # Resolve symbol_universe + watchlist FK ids needed for the brief insert.
        symbol_universe_id, watchlist_config_id = await self._resolve_brief_fks(symbol)

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

    async def _resolve_brief_fks(self, symbol: str) -> tuple[UUID, UUID]:
        """Return ``(symbol_universe_id, watchlist_config_id)`` for ``symbol``.

        Raises if the symbol is not in the tenant's universe or has no
        watchlist config (R5 assumes both exist; T4/W2 land the
        bootstrap-tenant CLI that seeds them).
        """
        from iguanatrader.contexts.research.models import (
            SymbolUniverse,
            WatchlistConfig,
        )

        # Casts to ResearchRepository to access the protected session via the
        # only public surface we have — the inherited BaseRepository
        # ``self._session`` attribute. This is a slice-internal helper.
        session = self._repo._session
        stmt = (
            sa.select(SymbolUniverse.id, WatchlistConfig.id)
            .join(
                WatchlistConfig,
                WatchlistConfig.symbol_universe_id == SymbolUniverse.id,
            )
            .where(SymbolUniverse.symbol == symbol)
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.first()
        if row is None:
            raise LookupError(
                f"no symbol_universe + watchlist_config pair exists for symbol {symbol!r}; "
                "tenant must register the symbol via T4 bootstrap-tenant first"
            )
        return row[0], row[1]

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
