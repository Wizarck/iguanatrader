"""Cross-cutting value objects — :class:`Money` is the only one for now.

Per design decision D3 (slice 2 ``shared-primitives``): Money is a
frozen dataclass with explicit currency tag; arithmetic is restricted
to the same currency; floats are rejected at construction time so a
caller never accidentally introduces IEEE-754 drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from iguanatrader.shared.decimal_utils import currency_precision, quantize
from iguanatrader.shared.errors import CurrencyMismatchError


@dataclass(frozen=True, slots=True, init=False)
class Money:
    """An exact monetary amount tagged with an ISO 4217 currency code.

    Construction accepts ``str``, ``int``, or :class:`Decimal` for the
    amount; ``float`` is explicitly rejected with :class:`TypeError`.
    The stored ``amount`` is always a :class:`Decimal`.

    .. code-block:: python

        Money(Decimal("100.00"), "USD")
        Money("100.00", "USD")        # str → Decimal (recommended)
        Money(100, "USD")             # int → Decimal (exact)
        Money(1.5, "USD")             # raises TypeError — floats forbidden

    Arithmetic between two :class:`Money` instances is restricted to the
    same currency; mixing raises :class:`CurrencyMismatchError`.
    Multiplication by ``int`` or :class:`Decimal` is supported (for
    sizing positions, applying percentages); ``float`` factors are
    rejected. Plain addition or subtraction with a non-Money operand
    follows Python's usual ``__add__`` / ``__radd__`` semantics — i.e.
    raises :class:`TypeError`.
    """

    amount: Decimal
    currency: str

    def __init__(self, amount: Decimal | int | str, currency: str) -> None:
        # Reject float explicitly (isinstance(amount, int) is True for bool;
        # bool is a subclass of int — accept that as a degenerate int case).
        if isinstance(amount, float):
            raise TypeError(
                "Money.amount must not be a float (use str/int/Decimal); "
                "floats lose precision in financial arithmetic"
            )
        if not isinstance(amount, Decimal | int | str):
            raise TypeError(
                f"Money.amount must be Decimal/int/str, got " f"{type(amount).__name__}"
            )
        if not isinstance(currency, str):
            raise TypeError(f"Money.currency must be a str, got " f"{type(currency).__name__}")

        decimal_amount = amount if isinstance(amount, Decimal) else Decimal(amount)
        normalised_currency = currency.upper()
        # Validate the currency code; raises ValidationError if unknown.
        currency_precision(normalised_currency)

        # Frozen dataclass forbids attribute assignment; bypass via
        # object.__setattr__ which is the documented escape hatch.
        object.__setattr__(self, "amount", decimal_amount)
        object.__setattr__(self, "currency", normalised_currency)

    def _check_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(f"cannot mix {self.currency} and {other.currency}")

    def __add__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._check_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._check_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __mul__(self, factor: object) -> Money:
        if isinstance(factor, float):
            raise TypeError(
                "cannot multiply Money by float (use Decimal/int); "
                "floats lose precision in financial arithmetic"
            )
        if not isinstance(factor, Decimal | int):
            return NotImplemented
        return Money(self.amount * Decimal(factor), self.currency)

    def __rmul__(self, factor: object) -> Money:
        return self.__mul__(factor)

    def quantize(self) -> Money:
        """Return a new ``Money`` rounded to the currency's minor-unit precision."""
        places = currency_precision(self.currency)
        return Money(quantize(self.amount, places), self.currency)


__all__ = ["Money"]
