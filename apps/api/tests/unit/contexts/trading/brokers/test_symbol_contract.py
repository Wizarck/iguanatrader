"""Per-symbol IBKR contract resolution (WS-3 UCITS cutover).

Locks the behaviour that matters for the cutover: the US watchlist is
byte-identical (SMART/USD), an opt-in override map redirects UCITS symbols to
their trading currency, partial entries fall back per field, and a malformed
env value degrades to "no overrides" rather than crashing the order /
market-data path.
"""

from __future__ import annotations

import pytest
from iguanatrader.contexts.trading.brokers.symbol_contract import (
    ContractParams,
    parse_overrides,
    resolve_contract_params,
)


def test_no_override_resolves_us_default() -> None:
    p = resolve_contract_params("AMD", overrides={})
    assert p == ContractParams(exchange="SMART", currency="USD")


def test_override_redirects_currency() -> None:
    overrides = parse_overrides('{"VUSA": {"currency": "GBP"}}')
    p = resolve_contract_params("VUSA", overrides=overrides)
    assert p.currency == "GBP"
    assert p.exchange == "SMART"  # exchange fell back to default


def test_override_is_case_insensitive() -> None:
    overrides = parse_overrides('{"vusa": {"currency": "GBP"}}')
    assert resolve_contract_params("VUSA", overrides=overrides).currency == "GBP"
    assert resolve_contract_params("vusa", overrides=overrides).currency == "GBP"


def test_full_override_sets_both_fields() -> None:
    overrides = parse_overrides('{"IGLN": {"exchange": "LSEETF", "currency": "USD"}}')
    p = resolve_contract_params("IGLN", overrides=overrides)
    assert p == ContractParams(exchange="LSEETF", currency="USD")


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_empty_input_yields_no_overrides(raw: str | None) -> None:
    assert parse_overrides(raw) == {}


def test_malformed_json_degrades_to_no_overrides() -> None:
    assert parse_overrides("{not json") == {}


def test_non_object_json_degrades_to_no_overrides() -> None:
    assert parse_overrides('["VUSA"]') == {}


def test_non_object_entry_is_skipped() -> None:
    overrides = parse_overrides('{"VUSA": "GBP", "IGLN": {"currency": "USD"}}')
    assert "VUSA" not in overrides  # bad entry skipped
    assert overrides["IGLN"].currency == "USD"


def test_resolve_reads_env_when_no_overrides_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_SYMBOL_CONTRACT_OVERRIDES", '{"VWRL": {"currency": "EUR"}}')
    assert resolve_contract_params("VWRL").currency == "EUR"
    assert resolve_contract_params("AMD").currency == "USD"  # unmapped → default


def test_adapter_build_contract_honours_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """The order path (IBKRAdapter._build_contract) routes a UCITS symbol to its
    currency while the US watchlist stays SMART/USD."""
    from iguanatrader.contexts.trading.brokers.ibkr_adapter import IBKRAdapter
    from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import IBKRBrokerageModel

    from tests._fakes.ib_async_fake import FakeIBClient

    monkeypatch.setenv("IGUANATRADER_SYMBOL_CONTRACT_OVERRIDES", '{"VUSA": {"currency": "GBP"}}')
    adapter = IBKRAdapter(
        brokerage=IBKRBrokerageModel.for_paper(), client_factory=lambda: FakeIBClient()
    )

    us = adapter._build_contract("AMD")
    assert (us.exchange, us.currency) == ("SMART", "USD")

    ucits = adapter._build_contract("VUSA")
    assert (ucits.exchange, ucits.currency) == ("SMART", "GBP")
