"""CLI smoke tests for ``iguanatrader market-data`` (slice T4-followup-market-data §9.3.1).

Heavy-import-free: only verifies that the Typer app registers the two
subcommands + their help text renders. Full subprocess-driven invocation
(end-to-end with DB + tenant + IBKR mock) is out of scope; the
ingestion flow is exercised by ``test_ingestion_service.py``.
"""

from __future__ import annotations

from iguanatrader.cli.market_data import app
from typer.testing import CliRunner


def test_help_lists_sync_and_backfill_subcommands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "sync" in result.output
    assert "backfill" in result.output


def test_sync_help_lists_expected_options() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["sync", "--help"])
    assert result.exit_code == 0, result.output
    assert "--symbols" in result.output
    assert "--timeframe" in result.output
    assert "--lookback-bars" in result.output


def test_backfill_help_lists_expected_options() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["backfill", "--help"])
    assert result.exit_code == 0, result.output
    assert "--symbol" in result.output
    assert "--days" in result.output
