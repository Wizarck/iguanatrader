"""Composition-root wiring for the LLM-driven event handlers.

Subscribes the four LLM-features keystones into the trading daemon's
in-process bus + scheduler:

* **A1 AutoExplainEnrichingDispatcher** — wraps :class:`ChannelDispatcher`
  so outbound approval-request messages carry a 2-3 paragraph narrative
  from :class:`ProposalExplainerService` before fanning out to Hermes.
* **A2 AutoRiskReviewOnCreateHandler** — bus subscriber on
  :class:`ProposalCreated`; above-threshold proposals get a
  :class:`ProposalRiskAssessor` review logged via the no-op persister
  (real DB persist comes with migration 0025).
* **A3 AutoJournalOnCloseHandler** — bus subscriber on
  :class:`TradeClosed`; writes a post-mortem narrative via
  :class:`TradeJournalWriter` + persists on ``trades.journal_narrative``.
* **I7 IngestSchedulerService** — registers the ingest cron routines on
  the shared APScheduler. The full 13-adapter source-factory map is
  built by ``cli/_ingest_factories.py`` (sec_edgar, fred, openbb,
  ibkr, finnhub, motley-fool, edgartools, plus the six previously-
  orphan adapters bea/bls/gdelt/openfda/vdem/wgi_world_bank).

Best-effort across the board: any handler exception is logged via
structlog and swallowed; the bus + downstream flows are NEVER blocked
by an LLM failure.

The wiring lives next to ``cli/trading.py`` rather than under
``contexts/`` because it crosses bounded-context lines — bridging the
trading repository to the research-context explainer, etc. Per the
project's composition-root rule, that's exactly where this glue
belongs.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from iguanatrader.contexts.approval.auto_explain import (
    AutoExplainEnrichingDispatcher,
    NarrativeProvider,
)
from iguanatrader.contexts.research.auto_risk_review import (
    AutoRiskReviewOnCreateHandler,
)
from iguanatrader.contexts.research.ingest_scheduler import (
    IngestRunRecorder,
    IngestSchedulerService,
)
from iguanatrader.contexts.research.proposal_advisor.explainer import (
    ProposalExplainerService,
)
from iguanatrader.contexts.research.proposal_advisor.risk import (
    ProposalRiskAssessor,
)
from iguanatrader.contexts.trading.auto_journal import (
    AutoJournalOnCloseHandler,
)
from iguanatrader.contexts.trading.events import ProposalCreated, TradeClosed
from iguanatrader.contexts.trading.journaling import TradeJournalWriter

if TYPE_CHECKING:
    from iguanatrader.contexts.approval.channels.types import (
        ApprovalRequestRow,
    )
    from iguanatrader.contexts.approval.dispatcher import ChannelDispatcher
    from iguanatrader.contexts.research.synthesis.llm_client import LLMClient
    from iguanatrader.contexts.trading.repository import (
        TradeProposalRepository,
        TradeRepository,
    )
    from iguanatrader.shared.messagebus import MessageBus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# A3 — JournalWriterLike adapter
# ---------------------------------------------------------------------------


class TradeJournalPersistAdapter:
    """Bridges :class:`TradeJournalWriter` (``.write``) to the
    ``JournalWriterLike`` Protocol expected by
    :class:`AutoJournalOnCloseHandler` (``.write_and_persist``).

    Idempotent: if the trade row already carries a ``journal_narrative``
    (e.g. operator already called the manual ``/journal`` route), the
    cached value is returned without a second LLM call.
    """

    def __init__(
        self,
        *,
        writer: TradeJournalWriter,
        trade_repo: TradeRepository,
    ) -> None:
        self._writer = writer
        self._trade_repo = trade_repo

    async def write_and_persist(self, *, trade_id: UUID) -> str:
        trade = await self._trade_repo.get_by_id(trade_id)
        if trade is None:
            raise LookupError(f"trade {trade_id} not found")
        if trade.journal_narrative:
            return str(trade.journal_narrative)
        result = await self._writer.write(
            trade_id=str(trade_id),
            symbol=trade.symbol,
            side=trade.side,
            quantity=trade.quantity,
            mode=trade.mode,
            opened_at=trade.opened_at,
            closed_at=trade.closed_at,
            exit_reason=trade.exit_reason,
            realised_pnl=trade.realised_pnl,
        )
        trade.journal_narrative = result.narrative
        trade.journal_generated_at = datetime.now(UTC)
        trade.journal_model = result.model
        return result.narrative


# ---------------------------------------------------------------------------
# A2 — ProposalLoaderLike adapter
# ---------------------------------------------------------------------------


class TradeProposalLoaderAdapter:
    """Bridges :class:`TradeProposalRepository.get_by_id` to the
    ``ProposalLoaderLike`` Protocol expected by
    :class:`AutoRiskReviewOnCreateHandler`.

    The :class:`TradeProposal` ORM row already exposes every field the
    Protocol's ``_ProposalSnapshot`` requires (symbol/side/quantity/
    entry_price_indicative/stop_price/confidence_score/mode/reasoning),
    so we return the row directly — no shape translation needed.
    """

    def __init__(self, *, proposal_repo: TradeProposalRepository) -> None:
        self._proposal_repo = proposal_repo

    async def load(self, proposal_id: Any) -> Any:
        pid = proposal_id if isinstance(proposal_id, UUID) else UUID(str(proposal_id))
        prop = await self._proposal_repo.get_by_id(pid)
        if prop is None:
            raise LookupError(f"proposal {proposal_id} not found")
        return prop


def build_risk_assessment_persister(
    *,
    proposal_repo: TradeProposalRepository,
) -> Any:
    """Return a :data:`RiskAssessmentPersister` that UPDATEs the proposal row.

    Slice ``a2-risk-review-persist`` closes the gap left by the original
    A2 wiring (no-op persister stub). The five risk_* columns now exist on
    ``trade_proposals`` (migration 0031) and the append-only listener
    permits them via the column whitelist. The persister translates the
    service-layer :class:`ProposalRiskAssessment` field names to the
    repository's ``set_risk_assessment`` keyword arguments; ``flags`` →
    ``risk_flags`` because the assessment dataclass dropped the ``risk_``
    prefix for readability while the column kept it for namespacing.
    """

    async def _persist(assessment: Any) -> None:
        pid = UUID(str(assessment.proposal_id))
        await proposal_repo.set_risk_assessment(
            proposal_id=pid,
            risk_score=int(assessment.risk_score),
            risk_flags=list(assessment.flags),
            risk_rationale=str(assessment.rationale or ""),
            risk_model=str(assessment.model),
        )

    return _persist


def build_risk_review_threshold_loader() -> Any:
    """Return a :data:`ThresholdLoader` that reads
    ``tenants.feature_flags["risk_review_confidence_threshold"]``.

    Slice ``a2-risk-review-persist`` — exposes the per-tenant override
    surface added in :class:`FeatureFlagsIn`. Loader returns ``None``
    when the tenant has not configured a value so the handler falls
    back to :data:`DEFAULT_CONFIDENCE_THRESHOLD`. A malformed value
    (bad cast) degrades silently to ``None`` so a misconfigured tenant
    does not break the bus delivery.
    """
    from decimal import Decimal, InvalidOperation

    from sqlalchemy import select

    from iguanatrader.persistence.models import Tenant
    from iguanatrader.shared.contextvars import session_var

    async def _load(tenant_id: Any) -> Decimal | None:
        session = session_var.get()
        if session is None:
            return None
        result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant is None or not tenant.feature_flags:
            return None
        raw = tenant.feature_flags.get("risk_review_confidence_threshold")
        if raw is None:
            return None
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return None

    return _load


# ---------------------------------------------------------------------------
# A1 — NarrativeProvider factory
# ---------------------------------------------------------------------------


def build_explainer_narrative_provider(
    *,
    explainer: ProposalExplainerService,
    proposal_repo: TradeProposalRepository,
) -> NarrativeProvider:
    """Returns a :data:`NarrativeProvider` that loads the proposal for
    the approval request and asks the explainer for a 2-3 paragraph
    rationale.

    Returns the empty string when the proposal can't be loaded — the
    A1 wrapper treats empty narratives as "skip attachment", so the
    inner dispatcher falls back to the legacy raw template.
    """

    async def _provider(request: ApprovalRequestRow) -> str:
        try:
            prop = await proposal_repo.get_by_id(request.proposal_id)
        except Exception as exc:
            logger.warning(
                "approval.auto_explain.proposal_load_failed",
                extra={
                    "request_id": str(request.id),
                    "proposal_id": str(request.proposal_id),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return ""
        if prop is None:
            return ""
        result = await explainer.explain(
            proposal_id=str(prop.id),
            symbol=prop.symbol,
            side=prop.side,
            quantity=prop.quantity,
            entry_price_indicative=prop.entry_price_indicative,
            stop_price=prop.stop_price,
            confidence_score=prop.confidence_score,
            mode=prop.mode,
            reasoning=prop.reasoning or {},
        )
        return result.narrative

    return _provider


# ---------------------------------------------------------------------------
# Top-level wiring entry
# ---------------------------------------------------------------------------


def wire_llm_handlers(
    *,
    bus: MessageBus,
    scheduler: Any,
    llm_client: LLMClient,
    inner_dispatcher: ChannelDispatcher,
    trade_repo: TradeRepository,
    proposal_repo: TradeProposalRepository,
    session_factory: Any,
    ingest_sources: dict[str, Any] | None = None,
    ingest_watchlist: Iterable[Any] | None = None,
    ingest_persist_drafts: Any | None = None,
    hindsight_client: Any | None = None,
) -> ChannelDispatcher:
    """Subscribe A1/A2/A3 handlers + bootstrap I7 scheduler.

    Returns the wrapped channel dispatcher (A1 narrative-enriching
    wrapper) which the caller should pass to :class:`ApprovalService`
    in place of the inner dispatcher.

    ``ingest_sources`` / ``ingest_watchlist`` / ``ingest_persist_drafts``
    are the three inputs the I7 :class:`IngestSchedulerService` needs to
    register real cron jobs. When ANY of them is None the scheduler is
    constructed but no jobs are registered (back-compat for tests that
    don't exercise the ingest path). The production daemon
    (``cli/trading.py``) builds all three via ``_ingest_factories``.
    """
    journal_writer = TradeJournalWriter(llm_client)
    explainer = ProposalExplainerService(llm_client)
    risk_assessor = ProposalRiskAssessor(llm_client)

    # A3 — auto-journal subscriber on TradeClosed.
    #
    # ``hindsight_client`` closes the Hindsight feedback loop: when an
    # operator passes the production :class:`HindsightPort` (typically
    # built by ``build_hindsight_adapter_from_env``), the journal
    # narrative is retained to the recall bank in addition to being
    # persisted on the trade row. Pre-slice this argument was None and
    # the handler fell back to ``_NoopHindsightClient`` — narrative
    # never made it to Hindsight, the recall side had nothing to draw
    # from. Tests + dev environments without a Hindsight server can
    # still pass None to keep the noop semantics.
    journal_adapter = TradeJournalPersistAdapter(
        writer=journal_writer,
        trade_repo=trade_repo,
    )
    journal_handler = AutoJournalOnCloseHandler(
        journal_writer=journal_adapter,
        hindsight_client=hindsight_client,
    )
    bus.subscribe(TradeClosed, journal_handler)
    logger.info(
        "composition.wire_llm_handlers.a3_journal_subscribed",
        extra={"hindsight_wired": hindsight_client is not None},
    )

    # A2 — auto-risk-review subscriber on ProposalCreated.
    #
    # Slice ``a2-risk-review-persist``: migration 0031 added the five
    # ``risk_*`` columns to ``trade_proposals`` and the append-only
    # listener now permits the UPDATE. The persister adapter writes the
    # assessment back so the A1 dispatcher (which reads the same row)
    # can embed risk in its Hermes payload. Pre-slice the persister was
    # a no-op stub; the assessment was logged but never reachable from
    # downstream consumers. The threshold loader reads the per-tenant
    # ``risk_review_confidence_threshold`` feature-flag so operators can
    # raise or lower the gate without redeploy.
    proposal_loader = TradeProposalLoaderAdapter(proposal_repo=proposal_repo)
    risk_persister = build_risk_assessment_persister(proposal_repo=proposal_repo)
    risk_threshold_loader = build_risk_review_threshold_loader()
    risk_handler = AutoRiskReviewOnCreateHandler(
        assessor=risk_assessor,
        loader=proposal_loader,
        persister=risk_persister,
        threshold_loader=risk_threshold_loader,
    )
    bus.subscribe(ProposalCreated, risk_handler)
    logger.info("composition.wire_llm_handlers.a2_risk_subscribed")

    # I7 — ingest scheduler. Recorder uses the session factory for
    # write-the-row-and-commit semantics independent of the daemon's
    # long-lived session. The full factory map + watchlist snapshot
    # come from ``cli/_ingest_factories.py`` in production; tests can
    # leave them None to skip registration.
    recorder = IngestRunRecorder(session_provider=session_factory)
    ingest_scheduler = IngestSchedulerService(recorder=recorder)
    if (
        ingest_persist_drafts is not None
        and ingest_sources is not None
        and ingest_watchlist is not None
    ):
        specs = ingest_scheduler.bootstrap_ingest_routines(
            scheduler=scheduler,
            watchlist=ingest_watchlist,
            sources=ingest_sources,
            persist_drafts=ingest_persist_drafts,
        )
        logger.info(
            "composition.wire_llm_handlers.i7_scheduler_constructed",
            extra={
                "sources_count": len(ingest_sources),
                "jobs_registered": len(specs),
            },
        )
    else:
        logger.info(
            "composition.wire_llm_handlers.i7_scheduler_skipped",
            extra={"reason": "no ingest sources/watchlist/persist callable provided"},
        )

    # A1 — wrap the channel dispatcher with narrative enrichment.
    narrative_provider = build_explainer_narrative_provider(
        explainer=explainer,
        proposal_repo=proposal_repo,
    )
    wrapped = AutoExplainEnrichingDispatcher(
        inner=inner_dispatcher,
        provider=narrative_provider,
    )
    logger.info("composition.wire_llm_handlers.a1_dispatcher_wrapped")
    return wrapped


__all__ = [
    "TradeJournalPersistAdapter",
    "TradeProposalLoaderAdapter",
    "build_explainer_narrative_provider",
    "build_risk_assessment_persister",
    "build_risk_review_threshold_loader",
    "wire_llm_handlers",
]
