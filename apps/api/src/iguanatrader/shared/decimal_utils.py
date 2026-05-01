"""Decimal helpers — banker's rounding + ISO 4217 currency precision.

Per design decision D3 (slice 2 ``shared-primitives``): money math uses
:class:`decimal.Decimal` with :data:`decimal.ROUND_HALF_EVEN` (banker's
rounding) at currency-specific precision. ``ROUND_HALF_HALF_EVEN``
minimises statistical bias compared to ``ROUND_HALF_UP``, which matters
for thousands-of-trades aggregations.

The :data:`_PRECISIONS` table is a curated subset of ISO 4217 minor-unit
exponents for the currencies iguanatrader is likely to encounter
(equities, FX majors, crypto). Add new entries on demand — there is no
need to ship the full ISO 4217 list. ``currency_precision`` raises
:class:`ValidationError` for unknown codes so a caller never silently
loses precision.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from iguanatrader.shared.errors import ValidationError

# Curated ISO 4217 minor-unit precision (number of fractional digits).
# Crypto codes use the convention adopted by major exchanges (Coinbase /
# Kraken / Binance) — 8 places for BTC, 18 for ETH internal accounting
# but 8 in user-facing balance displays.
_PRECISIONS: dict[str, int] = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "CHF": 2,
    "CAD": 2,
    "AUD": 2,
    "JPY": 0,
    "KRW": 0,
    "BTC": 8,
    "ETH": 8,
}


def currency_precision(currency: str) -> int:
    """Return the number of fractional digits for an ISO 4217 currency code.

    Raises :class:`ValidationError` if ``currency`` is not in the
    curated precision table. Callers MUST add the code to
    :data:`_PRECISIONS` rather than catching the error and guessing.
    """
    if not isinstance(currency, str):
        raise ValidationError(f"currency must be a str, got {type(currency).__name__}")
    code = currency.upper()
    if code not in _PRECISIONS:
        raise ValidationError(
            f"unknown currency code {currency!r}; add to _PRECISIONS in "
            "iguanatrader.shared.decimal_utils"
        )
    return _PRECISIONS[code]


def quantize(amount: Decimal, places: int) -> Decimal:
    """Quantize ``amount`` to ``places`` decimal places using banker's rounding.

    Raises :class:`ValidationError` if ``places`` is negative or
    ``amount`` is not a :class:`Decimal`. Use this rather than
    :meth:`Decimal.quantize` directly so the rounding mode is consistent
    project-wide.
    """
    if not isinstance(amount, Decimal):
        raise ValidationError(f"amount must be Decimal, got {type(amount).__name__}")
    if places < 0:
        raise ValidationError(f"places must be >= 0, got {places}")
    quantum = Decimal(1).scaleb(-places)
    return amount.quantize(quantum, rounding=ROUND_HALF_EVEN)


__all__ = ["currency_precision", "quantize"]
