"""#15: the trading daemon refuses LIVE mode without explicit confirmation."""

from __future__ import annotations

import pytest
from iguanatrader.cli.trading import app
from typer.testing import CliRunner

runner = CliRunner()


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
