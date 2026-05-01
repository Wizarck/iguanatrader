"""Unit tests for :mod:`iguanatrader.shared.decimal_utils`."""

from __future__ import annotations

from decimal import Decimal

import pytest
from iguanatrader.shared.decimal_utils import currency_precision, quantize
from iguanatrader.shared.errors import ValidationError


class TestCurrencyPrecision:
    @pytest.mark.parametrize(
        ("currency", "expected"),
        [
            ("USD", 2),
            ("EUR", 2),
            ("GBP", 2),
            ("JPY", 0),
            ("KRW", 0),
            ("BTC", 8),
            ("ETH", 8),
        ],
    )
    def test_known_currencies(self, currency: str, expected: int) -> None:
        assert currency_precision(currency) == expected

    def test_case_insensitive(self) -> None:
        assert currency_precision("usd") == currency_precision("USD")

    def test_unknown_currency_raises_validation(self) -> None:
        with pytest.raises(ValidationError, match="unknown currency"):
            currency_precision("XYZ")

    def test_non_str_raises_validation(self) -> None:
        with pytest.raises(ValidationError, match="must be a str"):
            currency_precision(12345)  # type: ignore[arg-type]


class TestQuantize:
    def test_bankers_rounding_half_to_even(self) -> None:
        # Classic banker's rounding: .5 rounds to nearest even.
        # 1.005 quantized to 2 places → 1.00 (zero is even, so round down)
        # 1.015 quantized to 2 places → 1.02 (two is even, so round up)
        assert quantize(Decimal("1.005"), 2) == Decimal("1.00")
        assert quantize(Decimal("1.015"), 2) == Decimal("1.02")
        assert quantize(Decimal("1.025"), 2) == Decimal("1.02")
        assert quantize(Decimal("1.035"), 2) == Decimal("1.04")

    def test_zero_places_truncates_to_int(self) -> None:
        assert quantize(Decimal("1.5"), 0) == Decimal("2")
        assert quantize(Decimal("2.5"), 0) == Decimal("2")  # banker's: round to even

    def test_eight_places_for_btc(self) -> None:
        q = quantize(Decimal("0.123456789"), 8)
        assert q == Decimal("0.12345679")

    def test_negative_places_raises(self) -> None:
        with pytest.raises(ValidationError, match="must be >= 0"):
            quantize(Decimal("1"), -1)

    def test_non_decimal_raises(self) -> None:
        with pytest.raises(ValidationError, match="must be Decimal"):
            quantize(1.5, 2)  # type: ignore[arg-type]

    def test_already_quantized_is_identity(self) -> None:
        assert quantize(Decimal("1.23"), 2) == Decimal("1.23")
