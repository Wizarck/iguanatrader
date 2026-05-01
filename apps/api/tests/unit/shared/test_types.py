"""Unit tests for :mod:`iguanatrader.shared.types` — :class:`Money`."""

from __future__ import annotations

from decimal import Decimal

import pytest
from iguanatrader.shared.errors import CurrencyMismatchError, ValidationError
from iguanatrader.shared.types import Money


class TestConstruction:
    def test_decimal_amount(self) -> None:
        m = Money(Decimal("100.00"), "USD")
        assert m.amount == Decimal("100.00")
        assert m.currency == "USD"

    def test_str_amount_coerced_to_decimal(self) -> None:
        m = Money("100.00", "USD")
        assert m.amount == Decimal("100.00")
        assert isinstance(m.amount, Decimal)

    def test_int_amount_coerced_to_decimal(self) -> None:
        m = Money(100, "USD")
        assert m.amount == Decimal("100")
        assert isinstance(m.amount, Decimal)

    def test_float_rejected(self) -> None:
        with pytest.raises(TypeError, match="must not be a float"):
            Money(100.0, "USD")  # type: ignore[arg-type]

    def test_other_types_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be Decimal"):
            Money(object(), "USD")  # type: ignore[arg-type]

    def test_non_str_currency_rejected(self) -> None:
        with pytest.raises(TypeError, match="currency must be a str"):
            Money(Decimal(100), 840)  # type: ignore[arg-type]

    def test_unknown_currency_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unknown currency"):
            Money(Decimal(100), "XYZ")

    def test_currency_normalised_to_upper(self) -> None:
        m = Money(Decimal(100), "usd")
        assert m.currency == "USD"

    def test_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        m = Money(Decimal(100), "USD")
        with pytest.raises(FrozenInstanceError):
            m.amount = Decimal(200)  # type: ignore[misc]


class TestArithmetic:
    def test_same_currency_add_is_exact(self) -> None:
        a = Money(Decimal("0.1"), "USD")
        b = Money(Decimal("0.2"), "USD")
        assert (a + b) == Money(Decimal("0.3"), "USD")

    def test_same_currency_sub(self) -> None:
        a = Money(Decimal(100), "USD")
        b = Money(Decimal(30), "USD")
        assert (a - b) == Money(Decimal(70), "USD")

    def test_neg(self) -> None:
        a = Money(Decimal(100), "USD")
        assert -a == Money(Decimal(-100), "USD")

    def test_cross_currency_add_raises(self) -> None:
        a = Money(Decimal(100), "USD")
        b = Money(Decimal(100), "EUR")
        with pytest.raises(CurrencyMismatchError, match="USD and EUR"):
            _ = a + b

    def test_cross_currency_sub_raises(self) -> None:
        a = Money(Decimal(100), "USD")
        b = Money(Decimal(100), "EUR")
        with pytest.raises(CurrencyMismatchError):
            _ = a - b

    def test_mul_by_int(self) -> None:
        m = Money(Decimal("1.50"), "USD")
        assert (m * 3) == Money(Decimal("4.50"), "USD")

    def test_mul_by_decimal(self) -> None:
        m = Money(Decimal(100), "USD")
        assert (m * Decimal("0.5")) == Money(Decimal("50.0"), "USD")

    def test_rmul(self) -> None:
        m = Money(Decimal(100), "USD")
        assert (3 * m) == Money(Decimal(300), "USD")

    def test_mul_by_float_raises(self) -> None:
        m = Money(Decimal(100), "USD")
        with pytest.raises(TypeError, match="cannot multiply Money by float"):
            _ = m * 1.5

    def test_add_with_non_money_returns_not_implemented(self) -> None:
        m = Money(Decimal(100), "USD")
        # Standard Python: when __add__ returns NotImplemented, the runtime
        # falls back to __radd__ on the rhs, then raises TypeError.
        with pytest.raises(TypeError):
            _ = m + 5


class TestQuantizeMethod:
    def test_usd_two_places_bankers_rounding(self) -> None:
        # 1.005 USD → 1.00 (banker's: round-half-to-even, 0 is even)
        assert Money("1.005", "USD").quantize() == Money(Decimal("1.00"), "USD")

    def test_jpy_zero_places(self) -> None:
        # JPY has 0 minor units; 100.5 → 100 (banker's: round to even)
        assert Money("100.5", "JPY").quantize() == Money(Decimal("100"), "JPY")
        assert Money("101.5", "JPY").quantize() == Money(Decimal("102"), "JPY")

    def test_btc_eight_places(self) -> None:
        m = Money("0.123456789", "BTC").quantize()
        assert m.amount == Decimal("0.12345679")

    def test_already_quantized_is_idempotent(self) -> None:
        m = Money(Decimal("100.00"), "USD")
        assert m.quantize() == m
