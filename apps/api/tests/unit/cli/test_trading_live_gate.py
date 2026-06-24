"""#15: the trading daemon refuses LIVE mode without explicit confirmation.

Two layers:
- The synchronous ``--confirm-live`` gate in ``run()`` (no DB) — covered by the
  CliRunner tests below.
- The DB-backed paper-history gate (AGENTS.md §7 override 2026-04-28): LIVE
  without recorded paper history needs ``--i-understand-the-risks`` and records
  the override in ``audit_log``. Covered by the helper tests (a fake audit repo
  keeps them DB-free).
"""

from __future__ import annotations

from typing import Any

import pytest
import typer
from iguanatrader.cli.trading import (
    _LIVE_OVERRIDE_EVENT,
    _PAPER_SESSION_EVENT,
    _enforce_live_paper_history_gate,
    _record_daemon_session_start,
    _session_started_event,
    app,
)
from typer.testing import CliRunner

runner = CliRunner()


class _FakeAuditRepo:
    """Duck-typed stand-in for ``AuditLogRepository`` (no DB)."""

    def __init__(self, *, paper_seen: bool = False) -> None:
        self._paper_seen = paper_seen
        self.inserted: list[Any] = []

    async def event_exists(self, event: str) -> bool:
        return self._paper_seen and event == _PAPER_SESSION_EVENT

    async def insert_for_tenant(self, entry: Any) -> None:
        self.inserted.append(entry)


class _StubLog:
    def error(self, *a: object, **k: object) -> None: ...
    def warning(self, *a: object, **k: object) -> None: ...
    def info(self, *a: object, **k: object) -> None: ...


def test_live_without_confirm_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``run`` is the sole command in this Typer app, so options are passed
    # without the subcommand name.
    monkeypatch.delenv("IGUANATRADER_CONFIRM_LIVE", raising=False)
    result = runner.invoke(app, ["--mode", "live"])
    # Exits 2 BEFORE booting the daemon (no DB/broker touched).
    assert result.exit_code == 2
    assert "confirm" in result.output.lower()


def test_live_with_env_confirm_passes_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    # With the env confirmation set, the gate passes and control reaches the
    # daemon body — which fails fast here (no DB/broker in the unit env).
    # We only assert the gate did NOT reject with our exit-2 + message.
    monkeypatch.setenv("IGUANATRADER_CONFIRM_LIVE", "true")
    result = runner.invoke(app, ["--mode", "live"])
    assert not (
        result.exit_code == 2 and "confirm" in result.output.lower()
    ), "gate should have passed with IGUANATRADER_CONFIRM_LIVE=true"


def test_invalid_mode_rejected() -> None:
    result = runner.invoke(app, ["--mode", "bogus"])
    assert result.exit_code == 2
    assert "invalid mode" in result.output.lower()


# --- paper-history gate (DB-backed layer, exercised via the pure helpers) ----


async def test_paper_mode_skips_gate_entirely() -> None:
    repo = _FakeAuditRepo(paper_seen=False)
    await _enforce_live_paper_history_gate(
        audit_repo=repo, mode="paper", i_understand_the_risks=False, log=_StubLog()
    )
    assert repo.inserted == []  # no override row; paper mode is a no-op


async def test_live_with_paper_history_passes_without_extra_flag() -> None:
    repo = _FakeAuditRepo(paper_seen=True)
    await _enforce_live_paper_history_gate(
        audit_repo=repo, mode="live", i_understand_the_risks=False, log=_StubLog()
    )
    assert repo.inserted == []  # prior paper history → no override needed


async def test_live_without_paper_history_blocks_when_unacknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IGUANATRADER_I_UNDERSTAND_THE_RISKS", raising=False)
    repo = _FakeAuditRepo(paper_seen=False)
    with pytest.raises(typer.Exit) as exc:
        await _enforce_live_paper_history_gate(
            audit_repo=repo, mode="live", i_understand_the_risks=False, log=_StubLog()
        )
    assert exc.value.exit_code == 2
    assert repo.inserted == []  # blocked → no override row written


async def test_live_without_paper_history_proceeds_with_flag_and_records_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IGUANATRADER_I_UNDERSTAND_THE_RISKS", raising=False)
    repo = _FakeAuditRepo(paper_seen=False)
    await _enforce_live_paper_history_gate(
        audit_repo=repo, mode="live", i_understand_the_risks=True, log=_StubLog()
    )
    assert len(repo.inserted) == 1
    row = repo.inserted[0]
    assert row.event == _LIVE_OVERRIDE_EVENT
    assert row.metadata_json["mode"] == "live"
    assert "risk_acknowledgment" in row.metadata_json


async def test_live_override_honours_env_acknowledgment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IGUANATRADER_I_UNDERSTAND_THE_RISKS", "true")
    repo = _FakeAuditRepo(paper_seen=False)
    await _enforce_live_paper_history_gate(
        audit_repo=repo, mode="live", i_understand_the_risks=False, log=_StubLog()
    )
    assert len(repo.inserted) == 1
    assert repo.inserted[0].event == _LIVE_OVERRIDE_EVENT


async def test_record_session_start_writes_mode_tagged_event() -> None:
    repo = _FakeAuditRepo()
    await _record_daemon_session_start(audit_repo=repo, mode="paper")
    assert len(repo.inserted) == 1
    assert repo.inserted[0].event == _session_started_event("paper")
    assert repo.inserted[0].event == _PAPER_SESSION_EVENT
