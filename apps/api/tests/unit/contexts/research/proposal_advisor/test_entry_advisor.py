"""WS-2 ``EntryAdvisor`` — entry-VETO opinion (runs on Opus).

Locks the model default (Opus — the owner reserves Opus for the risk-evaluation
judgement), the JSON verdict parsing, confidence clamping, and the conviction
default (a proceed verdict yields veto=False).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from iguanatrader.contexts.research.proposal_advisor.entry_advisor import (
    DEFAULT_ENTRY_MODEL,
    EntryAdvisor,
    EntryAdvisorParseError,
    EntryAdvisorVerdict,
)
from iguanatrader.contexts.research.synthesis.llm_client import LLMCompletion


class _StubLLM:
    def __init__(self, body: str) -> None:
        self._body = body
        self.last_model: str | None = None
        self.last_application: str | None = None

    async def complete(
        self,
        *,
        prompt: str,
        model: str,
        replay_key: str | None,
        max_tokens: int,
        langfuse_application: str = "iguanatrader-synthesis",
    ) -> LLMCompletion:
        self.last_model = model
        self.last_application = langfuse_application
        return LLMCompletion(
            text=self._body,
            tokens_input=10,
            tokens_output=20,
            cached=False,
            model=model,
        )


async def _assess(advisor: EntryAdvisor, **overrides: object) -> EntryAdvisorVerdict:
    kwargs: dict[str, object] = {
        "symbol": "AMD",
        "side": "buy",
        "quantity": Decimal("10"),
        "entry_price": Decimal("200"),
        "stop_price": Decimal("190"),
        "target_price": Decimal("240"),
        "confidence_score": Decimal("0.8"),
        "reasoning": {"lookback": 20, "breakout": "558.37"},
        "brief_thesis": "Thesis intact.",
        "hindsight_chunks": ["Prior AMD breakout faded into earnings."],
        "recent_trades_summary": "2 wins, 1 loss",
    }
    kwargs.update(overrides)
    return await advisor.assess(**kwargs)  # type: ignore[arg-type]


def test_default_model_is_opus() -> None:
    assert DEFAULT_ENTRY_MODEL == "claude-opus-4-8"


@pytest.mark.asyncio
async def test_veto_verdict_parsed_and_runs_on_opus() -> None:
    stub = _StubLLM(
        '{"veto": true, "confidence": 0.88, '
        '"rationale": "Long into a broken thesis ahead of earnings.", '
        '"flags": ["thesis_broken", "earnings_risk"]}'
    )
    advisor = EntryAdvisor(stub)  # type: ignore[arg-type]
    verdict = await _assess(advisor)

    assert verdict.veto is True
    assert verdict.confidence == Decimal("0.88")
    assert verdict.flags == ["thesis_broken", "earnings_risk"]
    assert "broken thesis" in verdict.rationale
    assert stub.last_model == "claude-opus-4-8"
    assert stub.last_application == "iguanatrader-entry"


@pytest.mark.asyncio
async def test_proceed_verdict_yields_false() -> None:
    stub = _StubLLM('{"veto": false, "confidence": 0.2, "rationale": "Looks fine."}')
    advisor = EntryAdvisor(stub)  # type: ignore[arg-type]
    verdict = await _assess(advisor)
    assert verdict.veto is False
    assert verdict.flags == []


@pytest.mark.asyncio
async def test_confidence_is_clamped_to_unit_interval() -> None:
    stub = _StubLLM('{"veto": true, "confidence": 7.5, "rationale": "x"}')
    advisor = EntryAdvisor(stub)  # type: ignore[arg-type]
    verdict = await _assess(advisor)
    assert verdict.confidence == Decimal("1")


@pytest.mark.asyncio
async def test_malformed_confidence_defaults_to_zero() -> None:
    stub = _StubLLM('{"veto": true, "confidence": "n/a", "rationale": "x"}')
    advisor = EntryAdvisor(stub)  # type: ignore[arg-type]
    verdict = await _assess(advisor)
    assert verdict.confidence == Decimal("0")


@pytest.mark.asyncio
async def test_non_json_body_raises_parse_error() -> None:
    stub = _StubLLM("Probably fine, hard to say.")
    advisor = EntryAdvisor(stub)  # type: ignore[arg-type]
    with pytest.raises(EntryAdvisorParseError):
        await _assess(advisor)


@pytest.mark.asyncio
async def test_json_embedded_in_prose_is_extracted() -> None:
    stub = _StubLLM('Sure: {"veto": true, "confidence": 0.9, "rationale": "block"} done.')
    advisor = EntryAdvisor(stub)  # type: ignore[arg-type]
    verdict = await _assess(advisor)
    assert verdict.veto is True
    assert verdict.confidence == Decimal("0.9")
