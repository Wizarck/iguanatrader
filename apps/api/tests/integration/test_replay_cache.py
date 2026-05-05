"""Integration tests for the replay cache (design D5).

Test matrix (per task 7.4):

- Hit returns recorded response.
- Miss raises :class:`ReplayCacheMissError`.
- Deterministic across N runs.
- Production mode (``IGUANATRADER_LLM_REPLAY`` unset) bypasses cache.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from iguanatrader.contexts.observability.errors import ReplayCacheMissError
from iguanatrader.contexts.observability.replay_cache import (
    REPLAY_FLAG_ENV,
    RecordedResponse,
    is_replay_mode,
    load_recorded_response,
    replay_cache,
    set_fixture_root_for_tests,
    write_recorded_response,
)


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    set_fixture_root_for_tests(tmp_path)
    yield tmp_path
    set_fixture_root_for_tests(None)


def test_hit_returns_recorded_response(fixture_root: Path) -> None:
    write_recorded_response(
        "scenario_a",
        RecordedResponse(tokens_input=11, tokens_output=22, content="hello"),
    )
    loaded = load_recorded_response("scenario_a")
    assert loaded.tokens_input == 11
    assert loaded.tokens_output == 22
    assert loaded.content == "hello"


def test_miss_raises_replay_cache_miss(fixture_root: Path) -> None:
    with pytest.raises(ReplayCacheMissError) as excinfo:
        load_recorded_response("not_recorded")
    assert "not_recorded" in (excinfo.value.detail or "")
    assert "IGUANATRADER_LLM_REPLAY_RECORD" in (excinfo.value.detail or "")


def test_deterministic_across_runs(fixture_root: Path) -> None:
    write_recorded_response(
        "deterministic",
        RecordedResponse(tokens_input=1, tokens_output=1, content="a"),
    )
    a = load_recorded_response("deterministic")
    b = load_recorded_response("deterministic")
    c = load_recorded_response("deterministic")
    assert a == b == c


def test_replay_mode_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REPLAY_FLAG_ENV, raising=False)
    assert is_replay_mode() is False
    monkeypatch.setenv(REPLAY_FLAG_ENV, "1")
    assert is_replay_mode() is True
    monkeypatch.setenv(REPLAY_FLAG_ENV, "0")
    assert is_replay_mode() is False


def test_context_manager_binds_and_resets_scenario() -> None:
    from iguanatrader.contexts.observability.replay_cache import current_scenario

    assert current_scenario.get() is None
    with replay_cache("xyz"):
        assert current_scenario.get() == "xyz"
    assert current_scenario.get() is None


def test_context_manager_resets_on_exception() -> None:
    from iguanatrader.contexts.observability.replay_cache import current_scenario

    with pytest.raises(RuntimeError):
        with replay_cache("xyz"):
            raise RuntimeError("body raised")
    assert current_scenario.get() is None
