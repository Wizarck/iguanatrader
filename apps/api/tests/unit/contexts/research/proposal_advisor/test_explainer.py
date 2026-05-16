"""Unit tests for :class:`ProposalExplainerService`."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from iguanatrader.contexts.research.proposal_advisor.explainer import (
    EXPLAINER_MAX_TOKENS,
    ProposalExplainerService,
)
from iguanatrader.contexts.research.synthesis.llm_client import (
    FakeLLMClient,
    LLMCompletion,
)


class _RecordingFake(FakeLLMClient):
    def __init__(self) -> None:
        super().__init__()
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
        self.calls.append(
            {
                "prompt": prompt,
                "model": model,
                "max_tokens": max_tokens,
                "langfuse_application": langfuse_application,
            }
        )
        return LLMCompletion(
            text="The proposal opens a long position on SPY because the donchian "
            "channel breakout triggered.\n\nRisk envelope: stop sits 2% below entry.\n\n"
            "Sanity check the ATR-multiplier setting before approving.",
            tokens_input=120,
            tokens_output=60,
            cached=False,
            model=model,
            replay_key=replay_key,
        )


@pytest.mark.asyncio
async def test_explain_passes_application_tag_and_max_tokens() -> None:
    fake = _RecordingFake()
    service = ProposalExplainerService(fake)

    result = await service.explain(
        proposal_id="11111111-1111-1111-1111-111111111111",
        symbol="SPY",
        side="buy",
        quantity=Decimal("10"),
        entry_price_indicative=Decimal("450.25"),
        stop_price=Decimal("440.00"),
        confidence_score=Decimal("0.75"),
        mode="paper",
        reasoning={"signal": "donchian"},
    )

    assert len(fake.calls) == 1
    call = fake.calls[0]
    # The explainer tag must reach the Langfuse layer so the dashboard
    # cost-by-application widget buckets correctly.
    assert call["langfuse_application"] == "iguanatrader-explainer"
    assert call["max_tokens"] == EXPLAINER_MAX_TOKENS
    assert "SPY" in call["prompt"]
    assert "donchian" in call["prompt"]
    assert result.narrative.startswith("The proposal opens")
    assert result.tokens_input == 120
    assert result.tokens_output == 60


@pytest.mark.asyncio
async def test_explain_handles_none_confidence_score() -> None:
    fake = _RecordingFake()
    service = ProposalExplainerService(fake)

    await service.explain(
        proposal_id="x",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        entry_price_indicative=Decimal("100"),
        stop_price=Decimal("99"),
        confidence_score=None,
        mode="paper",
        reasoning={},
    )

    assert "unspecified" in fake.calls[0]["prompt"]
