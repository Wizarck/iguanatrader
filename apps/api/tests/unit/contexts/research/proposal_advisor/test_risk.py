"""Unit tests for :class:`ProposalRiskAssessor`."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from iguanatrader.contexts.research.proposal_advisor.risk import (
    ProposalRiskAssessor,
    RiskAssessmentParseError,
)
from iguanatrader.contexts.research.synthesis.llm_client import (
    FakeLLMClient,
    LLMCompletion,
)


class _ScriptedFake(FakeLLMClient):
    def __init__(self, response_text: str) -> None:
        super().__init__()
        self._response_text = response_text
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        replay_key: str | None,
        max_tokens: int,
        langfuse_application: str = "iguanatrader-synthesis",
    ) -> LLMCompletion:
        self.calls.append({"langfuse_application": langfuse_application})
        return LLMCompletion(
            text=self._response_text,
            tokens_input=50,
            tokens_output=30,
            cached=False,
            model=model,
            replay_key=replay_key,
        )


@pytest.mark.asyncio
async def test_assess_parses_clean_json() -> None:
    fake = _ScriptedFake(
        '{"risk_score": 42, "flags": ["tight stop"], "rationale": "Stop is 0.5x ATR."}'
    )
    service = ProposalRiskAssessor(fake)

    result = await service.assess(
        proposal_id="11111111-1111-1111-1111-111111111111",
        symbol="SPY",
        side="buy",
        quantity=Decimal("10"),
        entry_price_indicative=Decimal("450.25"),
        stop_price=Decimal("449.00"),
        confidence_score=Decimal("0.6"),
        mode="paper",
        reasoning={"signal": "donchian"},
        recent_trades_summary="no recent trades",
        open_positions_count=0,
    )

    assert result.risk_score == 42
    assert result.flags == ["tight stop"]
    assert "Stop is 0.5x ATR" in result.rationale
    assert fake.calls[0]["langfuse_application"] == "iguanatrader-risk"


@pytest.mark.asyncio
async def test_assess_extracts_json_when_wrapped_in_prose() -> None:
    fake = _ScriptedFake(
        'Here is the JSON: {"risk_score": 75, "flags": [], "rationale": "ok"} done.'
    )
    service = ProposalRiskAssessor(fake)

    result = await service.assess(
        proposal_id="x",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        entry_price_indicative=Decimal("100"),
        stop_price=Decimal("99"),
        confidence_score=None,
        mode="paper",
        reasoning={},
        recent_trades_summary="",
        open_positions_count=0,
    )
    assert result.risk_score == 75


@pytest.mark.asyncio
async def test_assess_clips_score_to_0_100_range() -> None:
    fake = _ScriptedFake('{"risk_score": 200, "flags": [], "rationale": "x"}')
    service = ProposalRiskAssessor(fake)

    result = await service.assess(
        proposal_id="x",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        entry_price_indicative=Decimal("100"),
        stop_price=Decimal("99"),
        confidence_score=None,
        mode="paper",
        reasoning={},
        recent_trades_summary="",
        open_positions_count=0,
    )
    assert result.risk_score == 100


@pytest.mark.asyncio
async def test_assess_raises_parse_error_on_unparseable_body() -> None:
    fake = _ScriptedFake("totally not JSON, sorry")
    service = ProposalRiskAssessor(fake)

    with pytest.raises(RiskAssessmentParseError):
        await service.assess(
            proposal_id="x",
            symbol="SPY",
            side="buy",
            quantity=Decimal("1"),
            entry_price_indicative=Decimal("100"),
            stop_price=Decimal("99"),
            confidence_score=None,
            mode="paper",
            reasoning={},
            recent_trades_summary="",
            open_positions_count=0,
        )


@pytest.mark.asyncio
async def test_assess_caps_flags_at_five() -> None:
    fake = _ScriptedFake(
        '{"risk_score": 50, ' '"flags": ["a", "b", "c", "d", "e", "f", "g"], ' '"rationale": "x"}'
    )
    service = ProposalRiskAssessor(fake)

    result = await service.assess(
        proposal_id="x",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        entry_price_indicative=Decimal("100"),
        stop_price=Decimal("99"),
        confidence_score=None,
        mode="paper",
        reasoning={},
        recent_trades_summary="",
        open_positions_count=0,
    )
    assert len(result.flags) == 5
