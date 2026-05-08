"""Test that ``Synthesizer.synthesize`` accepts ``narrative_context`` and
prepends a Hindsight section to the prompt when it is non-empty
(slice R6 §2.3).

We mock the LLM client to capture the prompt; the rest of the pipeline
(citations + parse) is not exercised - this test isolates the prompt
composition.
"""

from __future__ import annotations

from typing import Any

import pytest


def _make_minimal_synthesizer() -> Any:
    """Lazy import so the test stays fast even if R5 internals shift."""
    from iguanatrader.contexts.research.synthesis import Synthesizer

    return Synthesizer


@pytest.mark.asyncio
async def test_narrative_context_prepended_to_prompt() -> None:
    Synthesizer = _make_minimal_synthesizer()

    captured: dict[str, str] = {}

    class _SpyLLM:
        async def complete(
            self,
            *,
            prompt: str,
            model: str,
            replay_key: str,
            max_tokens: int,
        ) -> Any:
            captured["prompt"] = prompt
            # Synthesizer downstream parsing requires a markdown body
            # of >=MIN_BODY_WORDS — we don't actually go that far in
            # this test (we'll catch the BriefSynthesisShortError).
            from iguanatrader.contexts.research.synthesis.anthropic_client import (
                LLMCompletion,
            )

            return LLMCompletion(
                text="short",
                input_tokens=1,
                output_tokens=1,
                cache_hit_tokens=0,
            )

    synth = Synthesizer(llm_client=_SpyLLM())  # type: ignore[arg-type]

    # Build a minimal feature_bundle + methodology_result.
    from iguanatrader.contexts.research.feature_provider import (
        FeatureBundle,
    )
    from iguanatrader.contexts.research.methodology import (
        METHODOLOGY_REGISTRY,
    )

    methodology = next(iter(METHODOLOGY_REGISTRY))
    bundle = FeatureBundle(
        symbol="AAPL",
        values={},
        fact_citations={},
        fact_lookups={},
    )
    score_fn = METHODOLOGY_REGISTRY[methodology]
    methodology_result = score_fn(bundle.values_only())

    # Test 1: with narrative_context populated, prompt prefixed.
    with pytest.raises(BaseException):  # noqa: B017 - downstream parse fails on stub LLM
        # Will raise BriefSynthesisShortError — that's fine; we just
        # need the prompt captured.
        await synth.synthesize(
            symbol="AAPL",
            methodology=methodology,
            feature_bundle=bundle,
            methodology_result=methodology_result,
            model="claude-3-5-sonnet",
            narrative_context=[
                "[brief_summary] AAPL theme: services growth",
                "[brief_summary] AAPL theme: hardware refresh cycle",
            ],
        )
    assert "Hindsight narrative" in captured["prompt"]
    assert "services growth" in captured["prompt"]

    # Test 2: with narrative_context=None, prompt does NOT include
    # the Hindsight block.
    captured.clear()
    with pytest.raises(BaseException):  # noqa: B017 - downstream parse fails on stub LLM
        await synth.synthesize(
            symbol="AAPL",
            methodology=methodology,
            feature_bundle=bundle,
            methodology_result=methodology_result,
            model="claude-3-5-sonnet",
            narrative_context=None,
        )
    assert "Hindsight narrative" not in captured["prompt"]
