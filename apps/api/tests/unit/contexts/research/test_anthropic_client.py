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
