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

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from iguanatrader.contexts.observability.budget import BudgetState, BudgetStatus
from iguanatrader.contexts.observability.errors import BudgetExceededError
from iguanatrader.contexts.research.synthesis import anthropic_client as ac_mod
from iguanatrader.contexts.research.synthesis.anthropic_client import (
    AnthropicLLMClient,
    build_anthropic_llm_client_from_env,
)
from iguanatrader.contexts.research.synthesis.llm_client import LLMCompletion
from iguanatrader.shared.contextvars import session_var, tenant_id_var


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
# Hard per-tenant LLM budget cutoff (flag-gated) — the "corte duro"
# ---------------------------------------------------------------------------


def _budget_state(status: BudgetStatus, percent: int) -> BudgetState:
    return BudgetState(
        tenant_id=uuid4(),
        status=status,
        percent_used=percent,
        spent_usd=Decimal("60.00"),
        cap_usd=Decimal("50.00"),
        remaining_usd=Decimal("0"),
    )


@pytest.mark.asyncio
async def test_budget_enforce_off_by_default_skips_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag OFF (default): check_budget is never consulted; call is served."""

    async def _must_not_run(*_a: Any, **_k: Any) -> BudgetState:
        raise AssertionError("check_budget must not run when enforcement is off")

    monkeypatch.setattr(ac_mod, "check_budget", _must_not_run)
    fake = _FakeAsyncAnthropic(_FakeMessage(text_blocks=["ok"], input_tokens=1, output_tokens=1))
    adapter = AnthropicLLMClient(api_key="sk", client=fake)  # type: ignore[arg-type]

    tok_t, tok_s = tenant_id_var.set(uuid4()), session_var.set(object())
    try:
        result = await adapter.complete(
            prompt="x", model="claude-opus-4-8", replay_key=None, max_tokens=8
        )
    finally:
        tenant_id_var.reset(tok_t)
        session_var.reset(tok_s)
    assert result.text == "ok"


@pytest.mark.asyncio
async def test_budget_enforce_blocks_over_cap_without_calling_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag ON + BLOCK_100 → raise BEFORE the SDK call, so no spend is recorded."""

    async def _block(*_a: Any, **_k: Any) -> BudgetState:
        return _budget_state(BudgetStatus.BLOCK_100, 120)

    monkeypatch.setattr(ac_mod, "check_budget", _block)
    fake = _FakeAsyncAnthropic(
        _FakeMessage(text_blocks=["should not happen"], input_tokens=1, output_tokens=1)
    )
    adapter = AnthropicLLMClient(api_key="sk", client=fake, enforce_budget=True)  # type: ignore[arg-type]

    tok_t, tok_s = tenant_id_var.set(uuid4()), session_var.set(object())
    try:
        with pytest.raises(BudgetExceededError):
            await adapter.complete(
                prompt="x", model="claude-opus-4-8", replay_key=None, max_tokens=8
            )
    finally:
        tenant_id_var.reset(tok_t)
        session_var.reset(tok_s)
    # The SDK was never invoked → the cost meter recorded nothing for the block.
    assert fake.messages.calls == []


@pytest.mark.asyncio
async def test_budget_enforce_allows_under_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok(*_a: Any, **_k: Any) -> BudgetState:
        return _budget_state(BudgetStatus.OK, 10)

    monkeypatch.setattr(ac_mod, "check_budget", _ok)
    fake = _FakeAsyncAnthropic(
        _FakeMessage(text_blocks=["served"], input_tokens=1, output_tokens=1)
    )
    adapter = AnthropicLLMClient(api_key="sk", client=fake, enforce_budget=True)  # type: ignore[arg-type]

    tok_t, tok_s = tenant_id_var.set(uuid4()), session_var.set(object())
    try:
        result = await adapter.complete(
            prompt="x", model="claude-opus-4-8", replay_key=None, max_tokens=8
        )
    finally:
        tenant_id_var.reset(tok_t)
        session_var.reset(tok_s)
    assert result.text == "served"


@pytest.mark.asyncio
async def test_budget_enforce_fail_open_without_tenant_or_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag ON but no tenant/session bound → cannot price cap → fail-OPEN."""

    async def _must_not_run(*_a: Any, **_k: Any) -> BudgetState:
        raise AssertionError("check_budget must not run without tenant context")

    monkeypatch.setattr(ac_mod, "check_budget", _must_not_run)
    fake = _FakeAsyncAnthropic(
        _FakeMessage(text_blocks=["served"], input_tokens=1, output_tokens=1)
    )
    adapter = AnthropicLLMClient(api_key="sk", client=fake, enforce_budget=True)  # type: ignore[arg-type]

    tok_t = tenant_id_var.set(None)  # explicitly no tenant
    try:
        result = await adapter.complete(
            prompt="x", model="claude-opus-4-8", replay_key=None, max_tokens=8
        )
    finally:
        tenant_id_var.reset(tok_t)
    assert result.text == "served"


def test_composition_root_helper_reads_budget_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")

    monkeypatch.setenv("IGUANATRADER_LLM_BUDGET_ENFORCE_ENABLED", "true")
    assert build_anthropic_llm_client_from_env()._enforce_budget is True

    monkeypatch.setenv("IGUANATRADER_LLM_BUDGET_ENFORCE_ENABLED", "off")
    assert build_anthropic_llm_client_from_env()._enforce_budget is False

    monkeypatch.delenv("IGUANATRADER_LLM_BUDGET_ENFORCE_ENABLED", raising=False)
    assert build_anthropic_llm_client_from_env()._enforce_budget is False


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
    # ``_GenerationWrapper.end(level="DEFAULT")`` translates to
    # ``update(level="DEFAULT")`` + ``end()`` per the v3 SDK shape.
    # First update carries usage_details (called pre-end); second carries
    # the level drained from end().
    usage_update = next(u for u in obs.updates if "usage_details" in u)
    assert usage_update["usage_details"]["input"] == 10
    assert usage_update["usage_details"]["output"] == 4
    level_update = next(u for u in obs.updates if u.get("level"))
    assert level_update["level"] == "DEFAULT"


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

    # Wrapper translates v2-style ``end(level="ERROR", status_message=...)``
    # into ``update(...)`` + ``end()`` per v3 SDK constraints.
    level_update = next(u for u in fake_lf.observations[-1].updates if u.get("level"))
    assert level_update["level"] == "ERROR"
    assert "RuntimeError" in level_update["status_message"]
