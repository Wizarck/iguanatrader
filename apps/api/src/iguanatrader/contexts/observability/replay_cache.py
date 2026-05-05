"""Test-mode-only LLM replay cache (per design D5).

Mode contract:

- ``IGUANATRADER_LLM_REPLAY=1`` → replay-mode active. The
  :func:`replay_cache` context manager binds a contextvars-scoped flag
  + scenario name; SDK adapters (slice R5+) detect the flag and route
  through :func:`load_recorded_response` instead of the real network
  call.
- Anything else → no-op. The context manager runs the body without any
  patching; production code paths see exactly what slice 5 saw.
- ``IGUANATRADER_LLM_REPLAY_RECORD=1`` (operator-driven, runbook gated)
  → record-mode. Recording writes the simplified response triple
  (``tokens_input``, ``tokens_output``, ``content``) to
  ``tests/fixtures/replay_cache/<scenario>.json``.

Cache miss in replay mode raises :class:`ReplayCacheMissError` with a
hint pointing to the runbook. Production mode never raises (it never
enters the cache code path).
"""

from __future__ import annotations

import contextvars
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from iguanatrader.contexts.observability.errors import ReplayCacheMissError

REPLAY_FLAG_ENV: str = "IGUANATRADER_LLM_REPLAY"
RECORD_FLAG_ENV: str = "IGUANATRADER_LLM_REPLAY_RECORD"

#: Default fixture root — overridable for tests via :func:`set_fixture_root_for_tests`.
_DEFAULT_FIXTURE_ROOT: Path = Path("apps/api/tests/fixtures/replay_cache")
_fixture_root: Path = _DEFAULT_FIXTURE_ROOT

#: contextvars-scoped scenario name; SDK adapters check ``current_scenario.get()``.
current_scenario: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "iguanatrader_replay_scenario",
    default=None,
)


@dataclass(frozen=True)
class RecordedResponse:
    """The simplified response triple recorded per scenario.

    Concrete LLM adapters project this onto the SDK-native response
    type (Anthropic Message, OpenAI ChatCompletion). Slice O1 plants
    the cache + the data shape; the projection is owned by slice R5
    (research brief synthesizer) when it lands the first real LLM
    adapter.
    """

    tokens_input: int
    tokens_output: int
    content: str


def is_replay_mode() -> bool:
    """``True`` iff ``IGUANATRADER_LLM_REPLAY=1`` is set."""
    return os.getenv(REPLAY_FLAG_ENV) == "1"


def is_record_mode() -> bool:
    """``True`` iff ``IGUANATRADER_LLM_REPLAY_RECORD=1`` is set."""
    return os.getenv(RECORD_FLAG_ENV) == "1"


def set_fixture_root_for_tests(path: Path | None) -> None:
    """Override the fixture root. Test-only helper; pass ``None`` to reset."""
    global _fixture_root
    _fixture_root = path or _DEFAULT_FIXTURE_ROOT


@contextmanager
def replay_cache(scenario: str) -> Iterator[None]:
    """Bind ``scenario`` for the duration of the ``with`` block.

    Production (``IGUANATRADER_LLM_REPLAY`` unset / "0"): no-op; the
    body runs against real LLM adapters.

    Test (``IGUANATRADER_LLM_REPLAY=1``): adapters detect the bound
    scenario and route through :func:`load_recorded_response`.

    The contextvar is reset on exit, even if the body raises.
    """
    token = current_scenario.set(scenario)
    try:
        yield
    finally:
        current_scenario.reset(token)


def load_recorded_response(scenario: str) -> RecordedResponse:
    """Load the recorded response for ``scenario`` from the fixture root.

    Raises :class:`ReplayCacheMissError` when the fixture file is
    absent. Production code never calls this (it's only reachable
    through the SDK adapters' replay branch when
    :func:`is_replay_mode` is true).
    """
    fixture_path = _fixture_root / f"{scenario}.json"
    if not fixture_path.exists():
        raise ReplayCacheMissError(
            detail=(
                f"No replay-cache fixture for scenario {scenario!r} at "
                f"{fixture_path}. Refresh via "
                f"`{RECORD_FLAG_ENV}=1 pytest "
                "tests/integration/test_replay_cache.py` "
                "(see docs/runbooks/replay-cache-refresh.md)."
            ),
        )
    with fixture_path.open("r", encoding="utf-8") as fp:
        raw = json.load(fp)
    return RecordedResponse(
        tokens_input=int(raw["tokens_input"]),
        tokens_output=int(raw["tokens_output"]),
        content=str(raw["content"]),
    )


def write_recorded_response(scenario: str, response: RecordedResponse) -> None:
    """Persist ``response`` for ``scenario`` under the fixture root.

    Used only in record-mode (``IGUANATRADER_LLM_REPLAY_RECORD=1``);
    callers MUST gate on :func:`is_record_mode` themselves. Creates
    the fixture root if it does not exist.
    """
    _fixture_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "tokens_input": response.tokens_input,
        "tokens_output": response.tokens_output,
        "content": response.content,
    }
    fixture_path = _fixture_root / f"{scenario}.json"
    with fixture_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, sort_keys=True)


__all__ = [
    "RECORD_FLAG_ENV",
    "REPLAY_FLAG_ENV",
    "RecordedResponse",
    "current_scenario",
    "is_record_mode",
    "is_replay_mode",
    "load_recorded_response",
    "replay_cache",
    "set_fixture_root_for_tests",
    "write_recorded_response",
]
