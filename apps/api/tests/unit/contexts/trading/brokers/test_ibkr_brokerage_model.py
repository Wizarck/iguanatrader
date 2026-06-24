"""Tests for :class:`IBKRBrokerageModel` (slice T2 design D8)."""

from __future__ import annotations

import pytest
from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import (
    SUPPORTED_ORDER_TYPES_DEFAULT,
    IBKRBrokerageModel,
    UnsupportedOrderTypeError,
    translate_order_type,
)


@pytest.mark.parametrize(
    ("domain", "ibkr"),
    [
        ("market", "MKT"),
        ("limit", "LMT"),
        ("stop", "STP"),
        ("stop_limit", "STP LMT"),
        # Idempotent: already-IBKR codes pass through unchanged.
        ("MKT", "MKT"),
        ("STP LMT", "STP LMT"),
        ("TRAIL", "TRAIL"),
    ],
)
def test_translate_order_type_maps_domain_to_ibkr(domain: str, ibkr: str) -> None:
    assert translate_order_type(domain) == ibkr


def test_translate_order_type_rejects_unknown() -> None:
    with pytest.raises(UnsupportedOrderTypeError):
        translate_order_type("teleport")


def test_paper_default_uses_port_7497() -> None:
    model = IBKRBrokerageModel.for_paper()
    assert model.port == 7497
    assert model.mode == "paper"


def test_live_requires_port_7496() -> None:
    model = IBKRBrokerageModel.for_live(account_code="U1234567")
    assert model.port == 7496
    assert model.mode == "live"
    assert model.account_code == "U1234567"


def test_paper_with_wrong_port_raises() -> None:
    with pytest.raises(ValueError, match="paper mode requires a paper port"):
        IBKRBrokerageModel(mode="paper", port=7496)


def test_live_with_wrong_port_raises() -> None:
    with pytest.raises(ValueError, match="live mode requires a live port"):
        IBKRBrokerageModel(mode="live", port=7497)


def test_paper_accepts_ib_gateway_port_4002() -> None:
    # 4002 is gnzsnz/ib-gateway's localhost-bound paper API (reachable
    # only from inside the gateway container itself).
    model = IBKRBrokerageModel(mode="paper", port=4002)
    assert model.port == 4002
    assert model.mode == "paper"


def test_live_accepts_ib_gateway_port_4001() -> None:
    model = IBKRBrokerageModel(mode="live", port=4001, account_code="U1234567")
    assert model.port == 4001
    assert model.mode == "live"


def test_paper_accepts_ib_gateway_socat_port_4004() -> None:
    # 4004 is the socat-exposed paper API that sibling containers (the
    # trading daemon) actually connect to — verified in prod: :4004
    # connects, :4002 times out from another container.
    model = IBKRBrokerageModel(mode="paper", port=4004)
    assert model.port == 4004
    assert model.mode == "paper"


def test_live_accepts_ib_gateway_socat_port_4003() -> None:
    model = IBKRBrokerageModel(mode="live", port=4003, account_code="U1234567")
    assert model.port == 4003
    assert model.mode == "live"


def test_from_env_reads_ibkr_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    # The compose deployment sets IBKR_HOST/IBKR_PORT (pointing at the
    # ib-gateway-paper container); from_env must honour them over the
    # mode-canonical TWS defaults.
    monkeypatch.setenv("IBKR_HOST", "ib-gateway-paper")
    monkeypatch.setenv("IBKR_PORT", "4004")
    model = IBKRBrokerageModel.from_env("paper")
    assert model.host == "ib-gateway-paper"
    assert model.port == 4004


def test_supported_order_types_default_is_canonical() -> None:
    assert frozenset({"MKT", "LMT", "STP", "STP LMT"}) == SUPPORTED_ORDER_TYPES_DEFAULT


def test_assert_supports_order_type_passes_for_whitelisted() -> None:
    model = IBKRBrokerageModel.for_paper()
    for order_type in SUPPORTED_ORDER_TYPES_DEFAULT:
        model.assert_supports_order_type(order_type)  # no raise.


def test_assert_supports_order_type_raises_for_blacklisted() -> None:
    model = IBKRBrokerageModel.for_paper()
    with pytest.raises(UnsupportedOrderTypeError) as exc_info:
        model.assert_supports_order_type("TRAIL")
    assert "TRAIL" in str(exc_info.value.detail)
    assert exc_info.value.type == "urn:iguanatrader:error:broker-order-type-unsupported"


def test_custom_supported_set_overrides_default() -> None:
    model = IBKRBrokerageModel(
        mode="paper",
        supported_order_types=frozenset({"MKT"}),
    )
    with pytest.raises(UnsupportedOrderTypeError):
        model.assert_supports_order_type("LMT")
    model.assert_supports_order_type("MKT")
