"""Shared position-sizing helper for all trading strategies.

Single source of truth for turning a signal + a risk/cash budget into a
WHOLE-SHARE quantity. IBKR rejects fractional bracket/STP quantities (and the
paper account is not fractional-enabled), so every mode floors DOWN to an
integer ``Decimal``. Callers keep their own ``quantity <= 0`` skip guard so a
budget that can't afford a single share is dropped rather than forced up to 1
(which would breach the risk envelope).

Two modes (selected by ``sizing_mode``):

* ``"risk"`` (default) — classic risk-per-trade sizing:
  ``floor(risk_pct * equity / abs(entry - stop))``. Flooring is the
  risk-conservative direction (actual risk <= the budgeted dollars).
* ``"cash"`` — fixed notional sizing, the way orders are often placed by hand
  at IB ("put $X into this name"): ``floor(target_cash / entry)``.

Any unrecognised mode falls back to ``"risk"`` so a malformed config can never
silently size by cash. Degenerate inputs (non-positive risk-per-share, entry,
or target_cash) return ``Decimal("0")`` rather than raising.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

SIZING_MODE_RISK = "risk"
SIZING_MODE_CASH = "cash"


def calculate_quantity(
    *,
    sizing_mode: str,
    entry: Decimal,
    stop: Decimal,
    risk_pct: Decimal,
    equity: Decimal,
    target_cash: Decimal,
) -> Decimal:
    """Whole-share position size, always floored DOWN to an integer ``Decimal``.

    Returns ``Decimal("0")`` for degenerate inputs; the caller applies its own
    ``quantity <= 0`` skip guard. The ``"risk"`` branch is byte-identical to the
    legacy inline sizing — ``risk_pct * equity`` is evaluated as a single
    sub-expression, divided by ``abs(entry - stop)``, then floored — so existing
    risk-mode behaviour (e.g. donchian live) is unchanged.
    """
    if sizing_mode == SIZING_MODE_CASH:
        if entry <= Decimal("0") or target_cash <= Decimal("0"):
            return Decimal("0")
        return (target_cash / entry).to_integral_value(rounding=ROUND_DOWN)

    # Default / unrecognised mode → risk-per-trade sizing.
    risk_per_share = abs(entry - stop)
    if risk_per_share <= Decimal("0"):
        return Decimal("0")
    risk_dollars = risk_pct * equity
    return (risk_dollars / risk_per_share).to_integral_value(rounding=ROUND_DOWN)


__all__ = ["SIZING_MODE_CASH", "SIZING_MODE_RISK", "calculate_quantity"]
