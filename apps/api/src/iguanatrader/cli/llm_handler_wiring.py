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
  the shared APScheduler. Source-factory map starts empty; a follow-up
  slice adds the per-adapter factories. The scheduler itself is wired
  now so subsequent factory additions are a one-line registration.

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
    ingest_persist_drafts: Any | None = None,
) -> ChannelDispatcher:
    """Subscribe A1/A2/A3 handlers + bootstrap I7 scheduler.

    Returns the wrapped channel dispatcher (A1 narrative-enriching
    wrapper) which the caller should pass to :class:`ApprovalService`
    in place of the inner dispatcher.

    ``ingest_persist_drafts`` is the bridge from I7 ``ResearchFactDraft``
    iterables to the research repository's insert path. When None, the
    scheduler is constructed but no source factories are registered —
    a deliberate hand-off point: the per-adapter factory map is wired
    in a follow-up slice once the ingest-source secrets surface is
    finalised. The bus subscriptions still fire today.
    """
    journal_writer = TradeJournalWriter(llm_client)
    explainer = ProposalExplainerService(llm_client)
    risk_assessor = ProposalRiskAssessor(llm_client)

    # A3 — auto-journal subscriber on TradeClosed.
    journal_adapter = TradeJournalPersistAdapter(
        writer=journal_writer,
        trade_repo=trade_repo,
    )
    journal_handler = AutoJournalOnCloseHandler(journal_writer=journal_adapter)
    bus.subscribe(TradeClosed, journal_handler)
    logger.info("composition.wire_llm_handlers.a3_journal_subscribed")

    # A2 — auto-risk-review subscriber on ProposalCreated.
    proposal_loader = TradeProposalLoaderAdapter(proposal_repo=proposal_repo)
    risk_handler = AutoRiskReviewOnCreateHandler(
        assessor=risk_assessor,
        loader=proposal_loader,
    )
    bus.subscribe(ProposalCreated, risk_handler)
    logger.info("composition.wire_llm_handlers.a2_risk_subscribed")

    # I7 — ingest scheduler. Recorder uses the session factory for
    # write-the-row-and-commit semantics independent of the daemon's
    # long-lived session. Sources dict starts empty; the follow-up
    # slice wires the per-adapter factories.
    recorder = IngestRunRecorder(session_provider=session_factory)
    ingest_scheduler = IngestSchedulerService(recorder=recorder)
    if ingest_persist_drafts is not None:
        ingest_scheduler.bootstrap_ingest_routines(
            scheduler=scheduler,
            watchlist=_load_watchlist_for_bootstrap(),
            sources={},
            persist_drafts=ingest_persist_drafts,
        )
    logger.info(
        "composition.wire_llm_handlers.i7_scheduler_constructed",
        extra={"sources_count": 0},
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


def _load_watchlist_for_bootstrap() -> Iterable[Any]:
    """Placeholder watchlist loader — returns an empty iterable today.

    Real implementation belongs in the follow-up slice that wires the
    per-adapter source factories; it'll query
    :class:`WatchlistConfigRepository` for enabled rows with a
    ``brief_refresh_schedule`` in {daily, weekly} OR a non-null
    ``brief_refresh_cron`` override.
    """
    return ()


__all__ = [
    "TradeJournalPersistAdapter",
    "TradeProposalLoaderAdapter",
    "build_explainer_narrative_provider",
    "wire_llm_handlers",
]
