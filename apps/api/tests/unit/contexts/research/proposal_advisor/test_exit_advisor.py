"""WS-5 PR-C: ``ExitAdvisor`` — urgent-exit OPINION (runs on Opus).

Locks the model default (Opus, not Sonnet — the owner reserves Opus for the
risk-evaluation opinion), the JSON verdict parsing, confidence clamping, and
the conviction default (a hold verdict yields urgent_sell=False).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from iguanatrader.contexts.research.proposal_advisor.exit_advisor import (
    DEFAULT_EXIT_MODEL,
    ExitAdvisor,
    ExitAdvisorParseError,
)
from iguanatrader.contexts.research.synthesis.llm_client import LLMCompletion


class _StubLLM:
    """Returns a fixed body + records the model it was asked to run on."""

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


async def _assess(advisor: ExitAdvisor, **overrides: object) -> object:
    kwargs: dict[str, object] = {
        "trade_id": "t-1",
        "symbol": "AMD",
        "side": "buy",
        "quantity": Decimal("10"),
        "average_price": Decimal("200"),
        "current_price": Decimal("180"),
        "unrealized_pnl": Decimal("-200"),
        "intended_stop": Decimal("190"),
        "intended_target": Decimal("240"),
        "resting_orders_summary": "none observed",
        "divergences": ["stop_missing_at_broker"],
        "brief_thesis": "Thesis intact.",
        "hindsight_chunks": ["Prior AMD drawdown after stop removal."],
        "recent_trades_summary": "2 wins, 1 loss",
    }
    kwargs.update(overrides)
    return await advisor.assess(**kwargs)  # type: ignore[arg-type]


def test_default_model_is_opus() -> None:
    # The owner's directive: the risk-evaluation OPINION runs on Opus.
    assert DEFAULT_EXIT_MODEL == "claude-opus-4-8"


@pytest.mark.asyncio
async def test_urgent_sell_verdict_parsed_and_runs_on_opus() -> None:
    stub = _StubLLM(
        '{"urgent_sell": true, "confidence": 0.86, '
        '"rationale": "Stop missing at broker while price falls.", '
        '"flags": ["unprotected", "adverse_move"]}'
    )
    advisor = ExitAdvisor(stub)  # type: ignore[arg-type]
    verdict = await _assess(advisor)

    assert verdict.urgent_sell is True
    assert verdict.confidence == Decimal("0.86")
    assert verdict.flags == ["unprotected", "adverse_move"]
    assert "Stop missing" in verdict.rationale
    # Ran on Opus, tagged for the exit cost bucket.
    assert stub.last_model == "claude-opus-4-8"
    assert stub.last_application == "iguanatrader-exit"


@pytest.mark.asyncio
async def test_hold_verdict_yields_false() -> None:
    stub = _StubLLM('{"urgent_sell": false, "confidence": 0.3, "rationale": "Thesis intact."}')
    advisor = ExitAdvisor(stub)  # type: ignore[arg-type]
    verdict = await _assess(advisor)
    assert verdict.urgent_sell is False
    assert verdict.flags == []


@pytest.mark.asyncio
async def test_confidence_is_clamped_to_unit_interval() -> None:
    stub = _StubLLM('{"urgent_sell": true, "confidence": 4.2, "rationale": "x"}')
    advisor = ExitAdvisor(stub)  # type: ignore[arg-type]
    verdict = await _assess(advisor)
    assert verdict.confidence == Decimal("1")


@pytest.mark.asyncio
async def test_malformed_confidence_defaults_to_zero() -> None:
    stub = _StubLLM('{"urgent_sell": false, "confidence": "n/a", "rationale": "x"}')
    advisor = ExitAdvisor(stub)  # type: ignore[arg-type]
    verdict = await _assess(advisor)
    assert verdict.confidence == Decimal("0")


@pytest.mark.asyncio
async def test_non_json_body_raises_parse_error() -> None:
    stub = _StubLLM("I think you should probably hold, hard to say.")
    advisor = ExitAdvisor(stub)  # type: ignore[arg-type]
    with pytest.raises(ExitAdvisorParseError):
        await _assess(advisor)


@pytest.mark.asyncio
async def test_json_embedded_in_prose_is_extracted() -> None:
    stub = _StubLLM('Sure: {"urgent_sell": true, "confidence": 0.7, "rationale": "go"} done.')
    advisor = ExitAdvisor(stub)  # type: ignore[arg-type]
    verdict = await _assess(advisor)
    assert verdict.urgent_sell is True
    assert verdict.confidence == Decimal("0.7")
