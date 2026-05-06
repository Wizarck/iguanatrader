"""Tests for :class:`IBKRBrokerageModel` (slice T2 design D8)."""

from __future__ import annotations

import pytest
from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import (
    SUPPORTED_ORDER_TYPES_DEFAULT,
    IBKRBrokerageModel,
    UnsupportedOrderTypeError,
)


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
    with pytest.raises(ValueError, match="paper mode requires port 7497"):
        IBKRBrokerageModel(mode="paper", port=7496)


def test_live_with_wrong_port_raises() -> None:
    with pytest.raises(ValueError, match="live mode requires port 7496"):
        IBKRBrokerageModel(mode="live", port=7497)


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
