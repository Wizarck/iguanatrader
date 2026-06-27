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


# --- con_id (authoritative key; removes the currency-guess) -------------------


def test_con_id_parsed_from_override() -> None:
    overrides = parse_overrides('{"VUSA": {"exchange": "LSEETF", "con_id": 107968728}}')
    p = resolve_contract_params("VUSA", overrides=overrides)
    assert p == ContractParams(exchange="LSEETF", currency="USD", con_id=107968728)


def test_con_id_accepts_numeric_string() -> None:
    overrides = parse_overrides('{"CRUD": {"exchange": "LSE", "con_id": "41015921"}}')
    assert resolve_contract_params("CRUD", overrides=overrides).con_id == 41015921


def test_con_id_invalid_degrades_to_none_without_dropping_entry() -> None:
    overrides = parse_overrides('{"VUSA": {"exchange": "LSEETF", "con_id": "nope"}}')
    p = resolve_contract_params("VUSA", overrides=overrides)
    assert p.con_id is None  # bad con_id ignored...
    assert p.exchange == "LSEETF"  # ...but the rest of the entry survives


def test_no_con_id_defaults_to_none() -> None:
    overrides = parse_overrides('{"VUSA": {"currency": "GBP"}}')
    assert resolve_contract_params("VUSA", overrides=overrides).con_id is None


def test_adapter_build_contract_threads_con_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """The order path carries the conId into the domain Contract."""
    from iguanatrader.contexts.trading.brokers.ibkr_adapter import IBKRAdapter
    from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import IBKRBrokerageModel

    from tests._fakes.ib_async_fake import FakeIBClient

    monkeypatch.setenv(
        "IGUANATRADER_SYMBOL_CONTRACT_OVERRIDES",
        '{"VUSA": {"exchange": "LSEETF", "con_id": 107968728}}',
    )
    adapter = IBKRAdapter(
        brokerage=IBKRBrokerageModel.for_paper(), client_factory=lambda: FakeIBClient()
    )
    c = adapter._build_contract("VUSA")
    assert (c.exchange, c.con_id) == ("LSEETF", 107968728)
    assert adapter._build_contract("AMD").con_id is None  # US watchlist unchanged


def test_translator_qualifies_stk_by_con_id() -> None:
    """When con_id is set, _to_contract qualifies by conId and leaves currency
    empty so a share-class guess can't contradict it."""
    pytest.importorskip("ib_async")
    from iguanatrader.contexts.trading.brokers.client_protocol import Contract
    from iguanatrader.contexts.trading.brokers.ib_async_client import _to_contract

    ib_c = _to_contract(Contract(symbol="VUSA", exchange="LSEETF", con_id=107968728))
    assert ib_c.conId == 107968728
    assert ib_c.currency == ""  # not forced — conId drives qualification
    assert ib_c.exchange == "LSEETF"

    # No con_id → legacy symbol+currency contract.
    legacy = _to_contract(Contract(symbol="AMD", exchange="SMART", currency="USD"))
    assert legacy.conId == 0  # ib_async default
    assert legacy.currency == "USD"
