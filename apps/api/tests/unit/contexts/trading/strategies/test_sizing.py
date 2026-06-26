"""Unit tests for the shared position-sizing helper (WS-A)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from iguanatrader.contexts.trading.strategies.sizing import (
    SIZING_MODE_CASH,
    SIZING_MODE_RISK,
    calculate_quantity,
)


@pytest.mark.parametrize(
    ("entry", "stop", "golden_qty"),
    [
        (Decimal("100"), Decimal("98"), Decimal("50")),  # rps=2 → floor(100/2)
        (Decimal("100"), Decimal("96.66667"), Decimal("30")),  # rps≈3.33333
        (Decimal("50"), Decimal("43"), Decimal("14")),  # rps=7 → floor(100/7)
        (Decimal("12.34"), Decimal("12.27"), Decimal("1428")),  # rps=0.07 → floor(100/0.07)
        (Decimal("200"), Decimal("186.3"), Decimal("7")),  # rps=13.7 → floor(100/13.7)
    ],
)
def test_risk_mode_matches_frozen_legacy_values(
    entry: Decimal, stop: Decimal, golden_qty: Decimal
) -> None:
    """Risk mode == the frozen pre-change donchian output. The golden integers
    are hard-coded (NOT recomputed from the production expression) so this test
    pins behaviour independently of how calculate_quantity is written — a future
    refactor that subtly changes the order of operations would fail here."""
    actual = calculate_quantity(
        sizing_mode=SIZING_MODE_RISK,
        entry=entry,
        stop=stop,
        risk_pct=Decimal("0.01"),
        equity=Decimal("10000"),
        target_cash=Decimal("0"),
    )
    assert actual == golden_qty


def test_risk_mode_result_is_always_integral() -> None:
    qty = calculate_quantity(
        sizing_mode=SIZING_MODE_RISK,
        entry=Decimal("100"),
        stop=Decimal("97"),
        risk_pct=Decimal("0.01"),
        equity=Decimal("10000"),
        target_cash=Decimal("0"),
    )
    assert qty == qty.to_integral_value()


def test_risk_mode_floors_to_zero_when_budget_below_one_share() -> None:
    qty = calculate_quantity(
        sizing_mode=SIZING_MODE_RISK,
        entry=Decimal("100"),
        stop=Decimal("90"),
        risk_pct=Decimal("0.01"),
        equity=Decimal("1"),  # risk_dollars = 0.01 over a $10 stop → < 1 share
        target_cash=Decimal("0"),
    )
    assert qty == Decimal("0")


def test_cash_mode_floors_target_cash_over_entry() -> None:
    qty = calculate_quantity(
        sizing_mode=SIZING_MODE_CASH,
        entry=Decimal("110"),
        stop=Decimal("100"),  # ignored in cash mode
        risk_pct=Decimal("0.01"),  # ignored
        equity=Decimal("10000"),  # ignored
        target_cash=Decimal("1000"),
    )
    assert qty == Decimal("9")  # floor(1000 / 110)
    assert qty == qty.to_integral_value()


def test_cash_mode_rounds_down_fractional_share() -> None:
    qty = calculate_quantity(
        sizing_mode=SIZING_MODE_CASH,
        entry=Decimal("100"),
        stop=Decimal("95"),
        risk_pct=Decimal("0.01"),
        equity=Decimal("10000"),
        target_cash=Decimal("999"),  # 9.99 shares → 9
    )
    assert qty == Decimal("9")


@pytest.mark.parametrize(
    ("sizing_mode", "entry", "stop", "target_cash"),
    [
        (SIZING_MODE_RISK, Decimal("100"), Decimal("100"), Decimal("0")),  # risk_per_share = 0
        (SIZING_MODE_CASH, Decimal("0"), Decimal("0"), Decimal("1000")),  # entry <= 0
        (SIZING_MODE_CASH, Decimal("100"), Decimal("95"), Decimal("0")),  # target_cash <= 0
    ],
)
def test_degenerate_inputs_return_zero(
    sizing_mode: str, entry: Decimal, stop: Decimal, target_cash: Decimal
) -> None:
    qty = calculate_quantity(
        sizing_mode=sizing_mode,
        entry=entry,
        stop=stop,
        risk_pct=Decimal("0.01"),
        equity=Decimal("10000"),
        target_cash=target_cash,
    )
    assert qty == Decimal("0")


def test_unknown_mode_falls_back_to_risk() -> None:
    """A malformed sizing_mode must NOT silently size by cash — it falls back to
    the risk path (a huge target_cash would otherwise dominate if cash ran)."""
    unknown = calculate_quantity(
        sizing_mode="bogus",
        entry=Decimal("100"),
        stop=Decimal("97"),
        risk_pct=Decimal("0.01"),
        equity=Decimal("10000"),
        target_cash=Decimal("999999"),
    )
    risk = calculate_quantity(
        sizing_mode=SIZING_MODE_RISK,
        entry=Decimal("100"),
        stop=Decimal("97"),
        risk_pct=Decimal("0.01"),
        equity=Decimal("10000"),
        target_cash=Decimal("999999"),
    )
    assert unknown == risk
    # And definitely not the cash result floor(999999 / 100) = 9999.
    assert unknown != Decimal("9999")
