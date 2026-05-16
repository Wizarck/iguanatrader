"""Unit tests for the Langfuse wrapper (slice ``llm-observability-and-signals``).

The Langfuse SaaS SDK v3 is the real dep but tests never hit the
network: we monkeypatch the module-level state so :func:`is_enabled`
returns False (no-op mode) for the disabled-state tests, and
substitute a recording stub for the enabled-state contract tests.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from iguanatrader.contexts.observability import langfuse_client as lc
from iguanatrader.shared.contextvars import tenant_id_var


@pytest.fixture(autouse=True)
def _reset_langfuse_state() -> Any:
    """Reset module-level state between tests so they stay isolated."""
    lc._client = None
    lc._enabled = False
    lc._env_tag = "test"
    yield
    lc._client = None
    lc._enabled = False
    lc._env_tag = "test"


def test_disabled_when_credentials_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    lc.init_langfuse("test")

    assert lc.is_enabled() is False
    assert lc.get_client() is None


def test_start_trace_returns_noop_when_disabled() -> None:
    lc._enabled = False
    lc._client = None

    trace = lc.start_trace(name="x", application="iguanatrader-synthesis")

    # No-op trace exposes the same surface as the real one.
    gen = trace.generation(name="inner", model="m")
    gen.update(output="hi")
    gen.end(level="DEFAULT")
    trace.update(metadata={"foo": "bar"})
    trace.end()


def test_start_generation_returns_noop_when_disabled() -> None:
    lc._enabled = False
    lc._client = None

    gen = lc.start_generation(
        name="anthropic.messages.create",
        model="claude-3-5-haiku-20241022",
        application="iguanatrader-synthesis",
    )
    gen.update(output="hi", usage_details={"input": 1, "output": 2})
    gen.end(level="DEFAULT")


# --------------------------------------------------------------------------- #
# Recording fakes — mirror the v3 SDK shape (start_observation chains)
# --------------------------------------------------------------------------- #


class _RecordingObservation:
    """Mirrors LangfuseSpan / LangfuseGeneration surface used by the wrapper."""

    def __init__(self, kind: str, kwargs: dict[str, Any]) -> None:
        self.kind = kind
        self.init_kwargs = kwargs
        self.updates: list[dict[str, Any]] = []
        self.ends: list[dict[str, Any]] = []
        self.children: list[_RecordingObservation] = []

    def start_observation(self, **kwargs: Any) -> _RecordingObservation:
        child = _RecordingObservation(kwargs.get("as_type", "span"), kwargs)
        self.children.append(child)
        return child

    def update(self, **kwargs: Any) -> _RecordingObservation:
        self.updates.append(kwargs)
        return self

    def end(self, **kwargs: Any) -> _RecordingObservation:
        self.ends.append(kwargs)
        return self


class _RecordingLangfuse:
    """Mirrors the v3 ``Langfuse`` client surface used by the wrapper."""

    def __init__(self) -> None:
        self.observations: list[_RecordingObservation] = []

    def start_observation(self, **kwargs: Any) -> _RecordingObservation:
        obs = _RecordingObservation(kwargs.get("as_type", "span"), kwargs)
        self.observations.append(obs)
        return obs

    def flush(self) -> None: ...


def test_start_generation_stamps_required_tags() -> None:
    fake = _RecordingLangfuse()
    lc._client = fake  # type: ignore[assignment]
    lc._enabled = True
    lc._env_tag = "paper"

    lc.start_generation(
        name="anthropic.messages.create",
        model="claude-3-5-haiku-20241022",
        application="iguanatrader-explainer",
        input_data="hi",
        metadata={"replay_key": None},
    )

    assert len(fake.observations) == 1
    obs = fake.observations[0]
    assert obs.kind == "generation"
    md = obs.init_kwargs["metadata"]
    # ELIGIA dashboard widgets aggregate by these three keys.
    assert md["consumer"] == "iguanatrader"
    assert md["application"] == "iguanatrader-explainer"
    assert md["env"] == "paper"
    # Caller's extras coexist with the canonical tags.
    assert md["replay_key"] is None


def test_start_trace_includes_tenant_id_from_contextvar() -> None:
    fake = _RecordingLangfuse()
    lc._client = fake  # type: ignore[assignment]
    lc._enabled = True
    lc._env_tag = "dev"

    tenant_id = uuid4()
    token = tenant_id_var.set(tenant_id)
    try:
        lc.start_trace(
            name="synthesizer.synthesize",
            application="iguanatrader-synthesis",
            metadata={"symbol": "SPY"},
        )
    finally:
        tenant_id_var.reset(token)

    assert len(fake.observations) == 1
    md = fake.observations[0].init_kwargs["metadata"]
    assert md["consumer"] == "iguanatrader"
    assert md["application"] == "iguanatrader-synthesis"
    assert md["tenant_id"] == str(tenant_id)
    assert md["symbol"] == "SPY"


def test_start_generation_nests_under_explicit_trace() -> None:
    fake = _RecordingLangfuse()
    lc._client = fake  # type: ignore[assignment]
    lc._enabled = True

    trace = lc.start_trace(
        name="synthesizer.synthesize",
        application="iguanatrader-synthesis",
    )
    lc.start_generation(
        name="anthropic.messages.create",
        model="claude-3-5-haiku-20241022",
        application="iguanatrader-synthesis",
        trace=trace,
    )

    # When a trace is passed, the generation is created via trace.generation()
    # (which forwards to start_observation on the parent), NOT as a new
    # top-level observation on the client.
    assert len(fake.observations) == 1  # only the trace lives at top level
    assert len(fake.observations[0].children) == 1  # the generation nests
    assert fake.observations[0].children[0].kind == "generation"


@pytest.mark.asyncio
async def test_traced_generation_records_error_level_on_exception() -> None:
    fake = _RecordingLangfuse()
    lc._client = fake  # type: ignore[assignment]
    lc._enabled = True

    @lc.traced_generation(
        name="failing.call",
        model="claude-3-5-haiku-20241022",
        application="iguanatrader-explainer",
    )
    async def _boom() -> None:
        raise RuntimeError("upstream blew up")

    with pytest.raises(RuntimeError, match="upstream blew up"):
        await _boom()

    # The wrapper's ``_GenerationWrapper.end(level=..., status_message=...)``
    # translates v2-style end kwargs into a v3-correct
    # ``update(level=..., status_message=...)`` + ``end()`` sequence.
    update_call = fake.observations[-1].updates[-1]
    assert update_call["level"] == "ERROR"
    assert "RuntimeError" in update_call["status_message"]


def test_generation_end_translates_v2_kwargs_into_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The v3 SDK's ``LangfuseGeneration.end()`` only accepts ``end_time``;
    iguanatrader call-sites pass ``level`` / ``status_message`` per the
    v2-style ergonomic shape. The wrapper drains the non-``end_time``
    kwargs into ``update()`` before calling ``end()``.
    """
    fake = _RecordingLangfuse()
    lc._client = fake  # type: ignore[assignment]
    lc._enabled = True

    gen = lc.start_generation(name="x", model="m", application="iguanatrader-explainer")
    gen.end(level="ERROR", status_message="boom", end_time=42)

    obs = fake.observations[0]
    # Update was called with the v2-style kwargs.
    assert obs.updates == [{"level": "ERROR", "status_message": "boom"}]
    # End was called with only the v3-accepted kwarg.
    assert obs.ends == [{"end_time": 42}]


def test_shutdown_is_idempotent_on_disabled_client() -> None:
    lc._client = None
    lc._enabled = False
    # Must not raise even when the client was never initialised.
    lc.shutdown_langfuse()
    assert lc.is_enabled() is False
