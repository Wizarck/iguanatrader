"""Unit tests for :class:`AnthropicLLMClient` (slice deployment-foundation §3.A).

The Anthropic SDK is a hard dep but we never instantiate the real
``AsyncAnthropic`` here — tests inject a fake client conforming to the
``messages.create`` shape. This keeps unit suite hermetic + fast and
avoids spurious network calls.

Construction-time secret reading is also mocked: tests pass an
explicit ``api_key`` string (or use the composition-root helper with
``monkeypatch.setenv``).
"""

from __future__ import annotations

from typing import Any

import pytest
from iguanatrader.contexts.research.synthesis.anthropic_client import (
    AnthropicLLMClient,
    build_anthropic_llm_client_from_env,
)
from iguanatrader.contexts.research.synthesis.llm_client import LLMCompletion


class _FakeUsage:
    def __init__(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(
        self,
        text_blocks: list[str],
        input_tokens: int,
        output_tokens: int,
        cache_read_input_tokens: int = 0,
    ) -> None:
        self.content = [_FakeTextBlock(t) for t in text_blocks]
        self.usage = _FakeUsage(input_tokens, output_tokens, cache_read_input_tokens)


class _FakeMessages:
    def __init__(self, response: _FakeMessage) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        return self._response


class _FakeAsyncAnthropic:
    def __init__(self, response: _FakeMessage) -> None:
        self.messages = _FakeMessages(response)


@pytest.mark.asyncio
async def test_complete_returns_llm_completion_with_usage_metrics() -> None:
    fake = _FakeAsyncAnthropic(
        _FakeMessage(
            text_blocks=["Hello from Claude."],
            input_tokens=42,
            output_tokens=8,
        )
    )
    adapter = AnthropicLLMClient(api_key="sk-ant-test", client=fake)  # type: ignore[arg-type]

    result = await adapter.complete(
        prompt="Say hello.",
        model="claude-3-5-haiku",
        replay_key="hello-world",
        max_tokens=64,
    )

    assert isinstance(result, LLMCompletion)
    assert result.text == "Hello from Claude."
    assert result.tokens_input == 42
    assert result.tokens_output == 8
    assert result.cached is False
    assert result.model == "claude-3-5-haiku"
    assert result.replay_key == "hello-world"
    assert fake.messages.calls == [
        {
            "model": "claude-3-5-haiku",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "Say hello."}],
        }
    ]


@pytest.mark.asyncio
async def test_complete_concatenates_multiple_text_blocks() -> None:
    fake = _FakeAsyncAnthropic(
        _FakeMessage(
            text_blocks=["First block. ", "Second block."],
            input_tokens=10,
            output_tokens=4,
        )
    )
    adapter = AnthropicLLMClient(api_key="sk-ant-test", client=fake)  # type: ignore[arg-type]

    result = await adapter.complete(
        prompt="x", model="claude-3-5-haiku", replay_key=None, max_tokens=16
    )

    assert result.text == "First block. Second block."


@pytest.mark.asyncio
async def test_complete_marks_cached_when_cache_read_tokens_present() -> None:
    fake = _FakeAsyncAnthropic(
        _FakeMessage(
            text_blocks=["Cached response."],
            input_tokens=100,
            output_tokens=10,
            cache_read_input_tokens=80,
        )
    )
    adapter = AnthropicLLMClient(api_key="sk-ant-test", client=fake)  # type: ignore[arg-type]

    result = await adapter.complete(
        prompt="x", model="claude-3-5-haiku", replay_key=None, max_tokens=16
    )

    assert result.cached is True


@pytest.mark.asyncio
async def test_complete_handles_empty_content_gracefully() -> None:
    fake = _FakeAsyncAnthropic(_FakeMessage(text_blocks=[], input_tokens=5, output_tokens=0))
    adapter = AnthropicLLMClient(api_key="sk-ant-test", client=fake)  # type: ignore[arg-type]

    result = await adapter.complete(
        prompt="x", model="claude-3-5-haiku", replay_key=None, max_tokens=16
    )

    assert result.text == ""


def test_composition_root_helper_uses_secret_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")

    client = build_anthropic_llm_client_from_env()

    assert isinstance(client, AnthropicLLMClient)
    assert client._api_key == "sk-ant-from-env"


# ---------------------------------------------------------------------------
# Slice ``llm-observability-and-signals`` — Langfuse instrumentation
# ---------------------------------------------------------------------------


class _RecordingObservation:
    """Mirrors the v3 LangfuseGeneration/LangfuseSpan surface used by the wrapper."""

    def __init__(self, kind: str, kwargs: dict[str, Any]) -> None:
        self.kind = kind
        self.init_kwargs = kwargs
        self.updates: list[dict[str, Any]] = []
        self.ends: list[dict[str, Any]] = []

    def start_observation(self, **kwargs: Any) -> _RecordingObservation:
        return _RecordingObservation(kwargs.get("as_type", "span"), kwargs)

    def update(self, **kwargs: Any) -> _RecordingObservation:
        self.updates.append(kwargs)
        return self

    def end(self, **kwargs: Any) -> _RecordingObservation:
        self.ends.append(kwargs)
        return self


class _RecordingLangfuse:
    def __init__(self) -> None:
        self.observations: list[_RecordingObservation] = []

    def start_observation(self, **kwargs: Any) -> _RecordingObservation:
        obs = _RecordingObservation(kwargs.get("as_type", "span"), kwargs)
        self.observations.append(obs)
        return obs

    def flush(self) -> None: ...


@pytest.mark.asyncio
async def test_complete_emits_langfuse_generation_with_canonical_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The AnthropicLLMClient must publish a Langfuse generation with
    ``consumer=iguanatrader`` + ``application=iguanatrader-synthesis``
    (the default) and the usage tokens so the ELIGIA cost widgets
    bucket the call correctly.
    """
    from iguanatrader.contexts.observability import langfuse_client as lc

    fake_lf = _RecordingLangfuse()
    monkeypatch.setattr(lc, "_client", fake_lf)
    monkeypatch.setattr(lc, "_enabled", True)
    monkeypatch.setattr(lc, "_env_tag", "test")

    fake_anthropic = _FakeAsyncAnthropic(
        _FakeMessage(text_blocks=["ok"], input_tokens=10, output_tokens=4)
    )
    adapter = AnthropicLLMClient(api_key="sk-ant-test", client=fake_anthropic)  # type: ignore[arg-type]

    await adapter.complete(prompt="x", model="claude-3-5-haiku", replay_key=None, max_tokens=16)

    assert len(fake_lf.observations) == 1
    obs = fake_lf.observations[0]
    assert obs.kind == "generation"
    md = obs.init_kwargs["metadata"]
    assert md["consumer"] == "iguanatrader"
    assert md["application"] == "iguanatrader-synthesis"
    # Span was closed with usage tokens + DEFAULT level (success path).
    update_call = obs.updates[-1]
    assert update_call["usage_details"]["input"] == 10
    assert update_call["usage_details"]["output"] == 4
    end_call = obs.ends[-1]
    assert end_call["level"] == "DEFAULT"


@pytest.mark.asyncio
async def test_complete_overrides_application_tag_when_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iguanatrader.contexts.observability import langfuse_client as lc

    fake_lf = _RecordingLangfuse()
    monkeypatch.setattr(lc, "_client", fake_lf)
    monkeypatch.setattr(lc, "_enabled", True)

    fake_anthropic = _FakeAsyncAnthropic(
        _FakeMessage(text_blocks=["ok"], input_tokens=1, output_tokens=1)
    )
    adapter = AnthropicLLMClient(api_key="sk-ant-test", client=fake_anthropic)  # type: ignore[arg-type]

    await adapter.complete(
        prompt="x",
        model="claude-3-5-haiku",
        replay_key=None,
        max_tokens=16,
        langfuse_application="iguanatrader-explainer",
    )

    assert (
        fake_lf.observations[0].init_kwargs["metadata"]["application"] == "iguanatrader-explainer"
    )


@pytest.mark.asyncio
async def test_complete_marks_error_level_on_anthropic_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iguanatrader.contexts.observability import langfuse_client as lc

    fake_lf = _RecordingLangfuse()
    monkeypatch.setattr(lc, "_client", fake_lf)
    monkeypatch.setattr(lc, "_enabled", True)

    class _Boom:
        class messages:
            @staticmethod
            async def create(**kwargs: Any) -> Any:
                raise RuntimeError("anthropic refused")

    adapter = AnthropicLLMClient(api_key="sk-ant-test", client=_Boom())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="anthropic refused"):
        await adapter.complete(prompt="x", model="claude-3-5-haiku", replay_key=None, max_tokens=8)

    end_call = fake_lf.observations[-1].ends[-1]
    assert end_call["level"] == "ERROR"
    assert "RuntimeError" in end_call["status_message"]
