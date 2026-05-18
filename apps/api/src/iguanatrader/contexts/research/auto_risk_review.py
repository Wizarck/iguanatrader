"""Auto-risk-review subscriber — slice A2.

Subscribes to :class:`ProposalCreated`; when the proposal's
``confidence_score`` exceeds the per-tenant threshold (default 0.80),
invokes :class:`ProposalRiskAssessor` and hands the result to an
injected persister callable. The future ``A2 migration 0020`` will
add ``risk_score / risk_flags / risk_rationale / risk_generated_at /
risk_model`` columns to ``trade_proposals``; until then the
persister is a no-op stub and the assessment is observable only via
structlog.

Best-effort semantics (same shape as A3 auto-journal):

* LLM failure (timeout, A0 budget cap hit, JSON parse error) →
  structlog ``research.auto_risk_review.failed`` + return. The
  proposal still proceeds to the approval flow unaffected.
* Persister failure → structlog
  ``research.auto_risk_review.persist_failed`` + swallow. The
  in-memory assessment is logged for postmortems.
* Confidence-score below threshold → silently skipped (cheap path —
  no LLM call, no log spam for the normal-flow case).

Threshold default is hardcoded at 0.80 to match the roadmap; a
follow-up surfaces it through ``tenants.feature_flags["risk_review_confidence_threshold"]``
once the per-tenant config UX lands.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from iguanatrader.contexts.research.proposal_advisor.risk import (
        ProposalRiskAssessment,
    )
    from iguanatrader.contexts.trading.events import ProposalCreated

logger = logging.getLogger(__name__)


#: Default confidence threshold. Tenants opt-in to more aggressive review
#: by lowering this via the feature-flags UI (slice A2-followup).
DEFAULT_CONFIDENCE_THRESHOLD: Decimal = Decimal("0.80")


class RiskAssessorLike(Protocol):
    """Structural type for :class:`ProposalRiskAssessor` — keeps tests
    free of the LLM client stack."""

    async def assess(
        self,
        *,
        proposal_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        entry_price_indicative: Decimal,
        stop_price: Decimal,
        confidence_score: Decimal | None,
        mode: str,
        reasoning: dict[str, Any],
        recent_trades_summary: str,
        open_positions_count: int,
    ) -> ProposalRiskAssessment: ...


class ProposalLoaderLike(Protocol):
    """Loader for the full proposal payload — composition root binds to
    :class:`TradeProposalRepository.get_by_id` or equivalent."""

    async def load(self, proposal_id: Any) -> _ProposalSnapshot: ...


class _ProposalSnapshot(Protocol):
    """Subset of the trade-proposal row the assessor consumes.

    Defined as a Protocol so the production model and a test fake can
    both satisfy it without inheritance — gives the handler a flat,
    documented input surface.
    """

    symbol: str
    side: str
    quantity: Decimal
    entry_price_indicative: Decimal
    stop_price: Decimal
    confidence_score: Decimal | None
    mode: str
    reasoning: dict[str, Any]


#: Persistence hook — composition root binds to a UPDATE on
#: ``trade_proposals`` once migration 0020 lands. Today a no-op stub
#: keeps the handler invocable.
RiskAssessmentPersister = Callable[["ProposalRiskAssessment"], Awaitable[None]]


async def _noop_persister(_assessment: ProposalRiskAssessment) -> None:
    """Default persister — logs the assessment so postmortems can
    grep for it even without DB columns yet."""
    logger.info(
        "research.auto_risk_review.persist_noop",
        extra={
            "proposal_id": _assessment.proposal_id,
            "risk_score": _assessment.risk_score,
            "flags": list(_assessment.flags),
            "rationale_preview": (_assessment.rationale or "")[:200],
            "model": _assessment.model,
        },
    )


class AutoRiskReviewOnCreateHandler:
    """Bus subscriber for :class:`ProposalCreated`.

    Two-stage flow:

    1. Load the full proposal payload via :class:`ProposalLoaderLike`
       (the event only carries the ID + symbol; assessor needs more).
    2. Compare ``confidence_score`` to ``threshold``. Sub-threshold →
       skip silently (cheap path).
    3. Above-threshold → ``assessor.assess(...)`` → ``persister(...)``.
    """

    def __init__(
        self,
        *,
        assessor: RiskAssessorLike,
        loader: ProposalLoaderLike,
        persister: RiskAssessmentPersister | None = None,
        threshold: Decimal = DEFAULT_CONFIDENCE_THRESHOLD,
        recent_trades_summary: str = "",
        open_positions_count: int = 0,
    ) -> None:
        self._assessor = assessor
        self._loader = loader
        self._persister = persister or _noop_persister
        self._threshold = threshold
        # Composition root can rebind these per-call via a future
        # extension if needed; the v1 contract uses the construction-
        # time values for every assessment.
        self._recent_trades_summary = recent_trades_summary
        self._open_positions_count = open_positions_count

    async def __call__(self, event: ProposalCreated) -> None:
        try:
            proposal = await self._loader.load(event.proposal_id)
        except Exception as exc:
            logger.warning(
                "research.auto_risk_review.load_failed",
                extra={
                    "proposal_id": str(event.proposal_id),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return

        confidence = proposal.confidence_score
        if confidence is None or confidence < self._threshold:
            # Sub-threshold → silent skip. No LLM call; no log spam.
            return

        try:
            assessment = await self._assessor.assess(
                proposal_id=str(event.proposal_id),
                symbol=proposal.symbol,
                side=proposal.side,
                quantity=proposal.quantity,
                entry_price_indicative=proposal.entry_price_indicative,
                stop_price=proposal.stop_price,
                confidence_score=confidence,
                mode=proposal.mode,
                reasoning=proposal.reasoning,
                recent_trades_summary=self._recent_trades_summary,
                open_positions_count=self._open_positions_count,
            )
        except Exception as exc:
            logger.warning(
                "research.auto_risk_review.failed",
                extra={
                    "proposal_id": str(event.proposal_id),
                    "symbol": event.symbol,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return

        try:
            await self._persister(assessment)
        except Exception as exc:
            logger.warning(
                "research.auto_risk_review.persist_failed",
                extra={
                    "proposal_id": str(event.proposal_id),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "AutoRiskReviewOnCreateHandler",
    "ProposalLoaderLike",
    "RiskAssessmentPersister",
    "RiskAssessorLike",
]
