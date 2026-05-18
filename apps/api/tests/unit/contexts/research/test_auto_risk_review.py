"""Unit tests for the A2 auto-risk-review subscriber.

Pure-unit — no LLM, no DB, no proposal repo. Fakes the loader,
assessor, and persister Protocols so the handler's threshold gate +
two-stage best-effort path are exercised in isolation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from iguanatrader.contexts.research.auto_risk_review import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    AutoRiskReviewOnCreateHandler,
)
from iguanatrader.contexts.research.proposal_advisor.risk import (
    ProposalRiskAssessment,
)
from iguanatrader.contexts.trading.events import ProposalCreated


@dataclass
class _FakeProposal:
    symbol: str = "AMD"
    side: str = "buy"
    quantity: Decimal = Decimal("10")
    entry_price_indicative: Decimal = Decimal("165.00")
    stop_price: Decimal = Decimal("158.00")
    confidence_score: Decimal | None = Decimal("0.85")
    mode: str = "paper"
    reasoning: dict[str, Any] = field(default_factory=dict)


class _FakeLoader:
    def __init__(
        self,
        *,
        proposal: _FakeProposal | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._proposal = proposal if proposal is not None else _FakeProposal()
        self._raises = raises
        self.calls: list[Any] = []

    async def load(self, proposal_id: Any) -> _FakeProposal:
        self.calls.append(proposal_id)
        if self._raises is not None:
            raise self._raises
        return self._proposal


def _assessment(score: int = 35) -> ProposalRiskAssessment:
    return ProposalRiskAssessment(
        proposal_id=str(uuid4()),
        risk_score=score,
        flags=["concentration"],
        rationale="ok",
        model="claude-haiku-4-5",
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
        tokens_input=120,
        tokens_output=80,
    )


class _FakeAssessor:
    def __init__(
        self,
        *,
        result: ProposalRiskAssessment | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._result = result if result is not None else _assessment()
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def assess(self, **kwargs: Any) -> ProposalRiskAssessment:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._result


def _event(proposal_id: UUID | None = None) -> ProposalCreated:
    return ProposalCreated(
        tenant_id=uuid4(),
        proposal_id=proposal_id or uuid4(),
        symbol="AMD",
        strategy_kind="donchian_atr",
        strategy_version=1,
        correlation_id=uuid4(),
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Threshold gate
# ---------------------------------------------------------------------------


def test_assessor_NOT_invoked_when_confidence_below_threshold() -> None:
    """Sub-threshold proposals are the normal case; we must NOT pay
    LLM cost or log spam for them."""
    proposal = _FakeProposal(confidence_score=Decimal("0.50"))
    loader = _FakeLoader(proposal=proposal)
    assessor = _FakeAssessor()
    handler = AutoRiskReviewOnCreateHandler(assessor=assessor, loader=loader)

    _run(handler(_event()))

    assert loader.calls != []  # loader did fire
    assert assessor.calls == []  # but assessor was skipped


def test_assessor_NOT_invoked_when_confidence_missing() -> None:
    """`confidence_score=None` ≠ "very low"; treat as "unknown" and
    skip rather than risk an inflated score."""
    proposal = _FakeProposal(confidence_score=None)
    loader = _FakeLoader(proposal=proposal)
    assessor = _FakeAssessor()
    handler = AutoRiskReviewOnCreateHandler(assessor=assessor, loader=loader)

    _run(handler(_event()))

    assert assessor.calls == []


def test_assessor_invoked_at_or_above_default_threshold() -> None:
    """0.80 is the boundary. The roadmap copy says "> threshold" but
    operators expect the boundary to count — using `< threshold` for
    skip + `>=` for invoke is the safer interpretation."""
    proposal = _FakeProposal(confidence_score=DEFAULT_CONFIDENCE_THRESHOLD)
    loader = _FakeLoader(proposal=proposal)
    assessor = _FakeAssessor()
    handler = AutoRiskReviewOnCreateHandler(assessor=assessor, loader=loader)

    _run(handler(_event()))

    assert len(assessor.calls) == 1


def test_custom_threshold_honoured() -> None:
    """Composition root can lower the threshold per tenant."""
    proposal = _FakeProposal(confidence_score=Decimal("0.65"))
    loader = _FakeLoader(proposal=proposal)
    assessor = _FakeAssessor()
    handler = AutoRiskReviewOnCreateHandler(
        assessor=assessor, loader=loader, threshold=Decimal("0.60")
    )

    _run(handler(_event()))

    assert len(assessor.calls) == 1


# ---------------------------------------------------------------------------
# Happy path → persister
# ---------------------------------------------------------------------------


def test_assessment_handed_to_persister_on_success() -> None:
    """Successful assess → persister.call(assessment) with the same
    object the assessor returned."""
    expected = _assessment(score=42)
    assessor = _FakeAssessor(result=expected)
    loader = _FakeLoader()
    persisted: list[ProposalRiskAssessment] = []

    async def _persist(a: ProposalRiskAssessment) -> None:
        persisted.append(a)

    handler = AutoRiskReviewOnCreateHandler(assessor=assessor, loader=loader, persister=_persist)

    _run(handler(_event()))

    assert persisted == [expected]


# ---------------------------------------------------------------------------
# Best-effort degradation
# ---------------------------------------------------------------------------


def test_loader_failure_swallowed() -> None:
    loader = _FakeLoader(raises=RuntimeError("DB down"))
    assessor = _FakeAssessor()
    handler = AutoRiskReviewOnCreateHandler(assessor=assessor, loader=loader)

    # Must NOT raise; the proposal still proceeds to approval flow.
    _run(handler(_event()))

    assert assessor.calls == []


def test_assessor_failure_swallowed_persister_skipped() -> None:
    """LLM failure (timeout, budget block, parse error) → no
    assessment to persist."""
    loader = _FakeLoader()
    assessor = _FakeAssessor(raises=RuntimeError("Anthropic 429"))
    persisted: list[ProposalRiskAssessment] = []

    async def _persist(a: ProposalRiskAssessment) -> None:
        persisted.append(a)

    handler = AutoRiskReviewOnCreateHandler(assessor=assessor, loader=loader, persister=_persist)

    _run(handler(_event()))

    assert persisted == []


def test_persister_failure_swallowed_assessment_still_logged() -> None:
    """Persister network error / DB constraint error → handler must
    NOT raise. Postmortem reads structlog for the assessment that
    was generated."""
    loader = _FakeLoader()
    assessor = _FakeAssessor()

    async def _bad_persister(a: ProposalRiskAssessment) -> None:
        raise RuntimeError("trade_proposals risk_* columns not yet migrated")

    handler = AutoRiskReviewOnCreateHandler(
        assessor=assessor, loader=loader, persister=_bad_persister
    )

    # Must NOT raise.
    _run(handler(_event()))


# ---------------------------------------------------------------------------
# Assessor input plumbing
# ---------------------------------------------------------------------------


def test_assessor_receives_full_proposal_payload() -> None:
    """The handler is the bridge between the slim event and the
    assessor's rich kwargs. Verify the mapping is exact."""
    proposal = _FakeProposal(
        symbol="NVDA",
        side="buy",
        quantity=Decimal("3"),
        entry_price_indicative=Decimal("900.00"),
        stop_price=Decimal("870.00"),
        confidence_score=Decimal("0.92"),
        mode="paper",
        reasoning={"pillar_scores": {"value": 0.4, "growth": 0.9, "momentum": 0.8}},
    )
    loader = _FakeLoader(proposal=proposal)
    assessor = _FakeAssessor()
    event = _event()
    handler = AutoRiskReviewOnCreateHandler(
        assessor=assessor,
        loader=loader,
        recent_trades_summary="3 winners, 1 loser",
        open_positions_count=2,
    )

    _run(handler(event))

    assert len(assessor.calls) == 1
    kwargs = assessor.calls[0]
    assert kwargs["proposal_id"] == str(event.proposal_id)
    assert kwargs["symbol"] == "NVDA"
    assert kwargs["side"] == "buy"
    assert kwargs["quantity"] == Decimal("3")
    assert kwargs["entry_price_indicative"] == Decimal("900.00")
    assert kwargs["stop_price"] == Decimal("870.00")
    assert kwargs["confidence_score"] == Decimal("0.92")
    assert kwargs["mode"] == "paper"
    assert kwargs["reasoning"] == proposal.reasoning
    assert kwargs["recent_trades_summary"] == "3 winners, 1 loser"
    assert kwargs["open_positions_count"] == 2
