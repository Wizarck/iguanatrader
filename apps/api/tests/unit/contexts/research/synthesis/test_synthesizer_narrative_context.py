"""Test that ``Synthesizer.synthesize`` accepts ``narrative_context``
and prepends a Hindsight section to the prompt when non-empty
(slice R6 §2.3).

We patch ``Synthesizer._render_prompt`` to return a deterministic
string and a spy ``LLMClient`` to capture the final prompt that is
sent to ``llm.complete``. This avoids needing real ``FeatureBundle`` /
``LLMCompletion`` shapes (those have project-specific signatures we
don't want to couple to here).
"""

from __future__ import annotations

from typing import Any

import pytest


class _RecordingLLM:
    """Minimal LLMClient spy that captures the final prompt."""

    def __init__(self) -> None:
        self.last_prompt: str | None = None

    async def complete(
        self,
        *,
        prompt: str,
        model: str,
        replay_key: str,
        max_tokens: int,
    ) -> Any:
        self.last_prompt = prompt
        # Return a sentinel; downstream parse will fail with a tractable
        # exception that the test catches.
        raise RuntimeError("STOP_AFTER_PROMPT_CAPTURE")


@pytest.mark.asyncio
async def test_synthesize_prepends_hindsight_block_when_context_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iguanatrader.contexts.research.synthesis.synthesizer import (
        Synthesizer,
    )

    spy = _RecordingLLM()
    synth = Synthesizer(llm_client=spy)  # type: ignore[arg-type]

    monkeypatch.setattr(
        Synthesizer,
        "_render_prompt",
        lambda *a, **kw: "ORIGINAL_PROMPT_BODY",
    )

    monkeypatch.setattr(
        Synthesizer,
        "_compute_replay_key",
        lambda *a, **kw: "key-x",
    )

    # Provide a methodology that exists; methodology_result is sentinel.
    from iguanatrader.contexts.research.methodology import (
        METHODOLOGY_REGISTRY,
    )

    methodology = next(iter(METHODOLOGY_REGISTRY))

    with pytest.raises(RuntimeError, match="STOP_AFTER_PROMPT_CAPTURE"):
        await synth.synthesize(
            symbol="AAPL",
            methodology=methodology,
            feature_bundle=object(),  # type: ignore[arg-type]
            methodology_result=object(),  # type: ignore[arg-type]
            model="claude-3-5-sonnet",
            narrative_context=[
                "[brief_summary] AAPL theme: services growth",
                "[brief_summary] AAPL theme: hardware refresh cycle",
            ],
        )

    assert spy.last_prompt is not None
    assert "Hindsight narrative" in spy.last_prompt
    assert "services growth" in spy.last_prompt
    # Original body still present after the prefix.
    assert "ORIGINAL_PROMPT_BODY" in spy.last_prompt
    # Hindsight block precedes the original.
    assert spy.last_prompt.index("Hindsight narrative") < spy.last_prompt.index(
        "ORIGINAL_PROMPT_BODY"
    )


@pytest.mark.asyncio
async def test_synthesize_omits_hindsight_block_when_context_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iguanatrader.contexts.research.synthesis.synthesizer import (
        Synthesizer,
    )

    spy = _RecordingLLM()
    synth = Synthesizer(llm_client=spy)  # type: ignore[arg-type]

    monkeypatch.setattr(
        Synthesizer,
        "_render_prompt",
        lambda *a, **kw: "ORIGINAL_PROMPT_BODY",
    )
    monkeypatch.setattr(
        Synthesizer,
        "_compute_replay_key",
        lambda *a, **kw: "key-x",
    )

    from iguanatrader.contexts.research.methodology import (
        METHODOLOGY_REGISTRY,
    )

    methodology = next(iter(METHODOLOGY_REGISTRY))

    with pytest.raises(RuntimeError, match="STOP_AFTER_PROMPT_CAPTURE"):
        await synth.synthesize(
            symbol="AAPL",
            methodology=methodology,
            feature_bundle=object(),  # type: ignore[arg-type]
            methodology_result=object(),  # type: ignore[arg-type]
            model="claude-3-5-sonnet",
            narrative_context=None,
        )

    assert spy.last_prompt is not None
    assert "Hindsight narrative" not in spy.last_prompt
    assert spy.last_prompt == "ORIGINAL_PROMPT_BODY"
