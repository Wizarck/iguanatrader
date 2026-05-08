"""Smoke tests for ``iguanatrader settings feature-flag`` CLI (slice R6).

Heavy-import-free: only exercises the Typer surface (``--help`` +
argument parsing). Full end-to-end DB invocation is covered by the
settings route tests.
"""

from __future__ import annotations

from iguanatrader.cli.settings import app
from typer.testing import CliRunner


def test_help_lists_feature_flag_subcommand() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "feature-flag" in result.output


def test_feature_flag_help_lists_get_and_set() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["feature-flag", "--help"])
    assert result.exit_code == 0, result.output
    assert "get" in result.output
    assert "set" in result.output


def test_feature_flag_set_rejects_unknown_key() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["feature-flag", "set", "made_up_flag=true"],
    )
    assert result.exit_code == 2, result.output
    assert "Unknown flag" in result.output or "Unknown flag" in result.stderr


def test_feature_flag_set_rejects_invalid_bool() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["feature-flag", "set", "hindsight_recall_enabled=banana"],
    )
    assert result.exit_code == 2, result.output
