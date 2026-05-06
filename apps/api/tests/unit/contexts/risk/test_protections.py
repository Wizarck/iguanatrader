"""Per-protection unit tests with edge-case coverage.

Each of the 5 protections is exercised at:

* The exact-cap boundary (allow vs reject).
* Trivial below-cap (allow).
* Above-cap (reject + correct ``cap_type_breached`` + ``current_pct``).
* Zero-capital + zero-cap edge cases.

The composed engine is tested separately in
:mod:`apps.api.tests.unit.contexts.risk.test_engine_composition`.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from iguanatrader.contexts.risk.models import (
    RiskCaps,
    RiskState,
    TradeProposalInput,
)
from iguanatrader.contexts.risk.protections import (
    daily,
    max_drawdown,
    max_open,
    per_trade,
    weekly,
)


def _make_proposal(notional: str | Decimal) -> TradeProposalInput:
    return TradeProposalInput(
        id=uuid4(),
        tenant_id=uuid4(),
        notional_value=Decimal(notional),
        side="buy",
    )


def _make_state(
    *,
    capital: str | Decimal = "100000",
    daily_loss: str | Decimal = "0",
    weekly_loss: str | Decimal = "0",
    open_positions: int = 0,
    drawdown: str | Decimal = "0",
) -> RiskState:
    return RiskState(
        capital=Decimal(capital),
        day_to_date_loss_pct=Decimal(daily_loss),
        week_to_date_loss_pct=Decimal(weekly_loss),
        open_positions_count=open_positions,
        peak_to_trough_drawdown_pct=Decimal(drawdown),
    )


# ---------------------------------------------------------------------------
# per_trade
# ---------------------------------------------------------------------------


def test_per_trade_allow_below_cap() -> None:
    caps = RiskCaps()
    state = _make_state(capital="100000")
    proposal = _make_proposal("1000")  # 1% of capital — below 2% cap.
    decision = per_trade.evaluate(proposal, state, caps)
    assert decision.outcome == "allow"
    assert decision.cap_type_breached is None


def test_per_trade_allow_at_exact_cap() -> None:
    """Boundary: at-cap (exactly 2% of capital) is ALLOWED.

    Per spec: rejection condition is "strictly greater than" the cap.
    """
    caps = RiskCaps()
    state = _make_state(capital="100000")
    proposal = _make_proposal("2000")  # exactly 2%
    decision = per_trade.evaluate(proposal, state, caps)
    assert decision.outcome == "allow"


def test_per_trade_reject_above_cap() -> None:
    caps = RiskCaps()
    state = _make_state(capital="100000")
    proposal = _make_proposal("2500")  # 2.5% > 2% cap
    decision = per_trade.evaluate(proposal, state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "per_trade"
    assert decision.current_pct == Decimal("0.025")


def test_per_trade_reject_zero_capital() -> None:
    """Zero capital: no trade allowed regardless of notional."""
    caps = RiskCaps()
    state = _make_state(capital="0")
    proposal = _make_proposal("1")
    decision = per_trade.evaluate(proposal, state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "per_trade"


# ---------------------------------------------------------------------------
# daily
# ---------------------------------------------------------------------------


def test_daily_allow_below_cap() -> None:
    caps = RiskCaps()
    state = _make_state(daily_loss="0.04")
    decision = daily.evaluate(_make_proposal("100"), state, caps)
    assert decision.outcome == "allow"


def test_daily_reject_at_cap() -> None:
    """Cap is at-or-above (>=), so exact 5% triggers rejection."""
    caps = RiskCaps()
    state = _make_state(daily_loss="0.05")
    decision = daily.evaluate(_make_proposal("100"), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "daily_loss"


def test_daily_reject_above_cap() -> None:
    caps = RiskCaps()
    state = _make_state(daily_loss="0.051")
    decision = daily.evaluate(_make_proposal("100"), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "daily_loss"
    assert decision.current_pct == Decimal("0.051")


# ---------------------------------------------------------------------------
# weekly
# ---------------------------------------------------------------------------


def test_weekly_allow_below_cap() -> None:
    caps = RiskCaps()
    state = _make_state(weekly_loss="0.10")
    decision = weekly.evaluate(_make_proposal("100"), state, caps)
    assert decision.outcome == "allow"


def test_weekly_reject_at_cap() -> None:
    caps = RiskCaps()
    state = _make_state(weekly_loss="0.15")
    decision = weekly.evaluate(_make_proposal("100"), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "weekly_loss"


# ---------------------------------------------------------------------------
# max_open
# ---------------------------------------------------------------------------


def test_max_open_allow_below_cap() -> None:
    caps = RiskCaps()  # default 10
    state = _make_state(open_positions=5)
    decision = max_open.evaluate(_make_proposal("100"), state, caps)
    assert decision.outcome == "allow"


def test_max_open_reject_at_cap() -> None:
    caps = RiskCaps()
    state = _make_state(open_positions=10)
    decision = max_open.evaluate(_make_proposal("100"), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "max_open"


def test_max_open_zero_cap_blocks_all() -> None:
    """``max_open_positions = 0`` blocks every proposal — defensive."""
    caps = RiskCaps(max_open_positions=0)
    state = _make_state(open_positions=0)
    decision = max_open.evaluate(_make_proposal("100"), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "max_open"


# ---------------------------------------------------------------------------
# max_drawdown
# ---------------------------------------------------------------------------


def test_max_drawdown_allow_below_cap() -> None:
    caps = RiskCaps()
    state = _make_state(drawdown="0.10")
    decision = max_drawdown.evaluate(_make_proposal("100"), state, caps)
    assert decision.outcome == "allow"


def test_max_drawdown_reject_at_cap() -> None:
    caps = RiskCaps()
    state = _make_state(drawdown="0.15")
    decision = max_drawdown.evaluate(_make_proposal("100"), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "max_drawdown"


def test_max_drawdown_reject_above_cap() -> None:
    caps = RiskCaps()
    state = _make_state(drawdown="0.155")
    decision = max_drawdown.evaluate(_make_proposal("100"), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "max_drawdown"


# ---------------------------------------------------------------------------
# Composition / engine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state_kwargs", "expected"),
    [
        ({"daily_loss": "0.06"}, "daily_loss"),
        ({"weekly_loss": "0.20"}, "weekly_loss"),
        ({"open_positions": 12}, "max_open"),
        ({"drawdown": "0.16"}, "max_drawdown"),
    ],
)
def test_engine_short_circuits_on_first_breach(
    state_kwargs: dict[str, str | int],
    expected: str,
) -> None:
    """Engine returns the first non-allow Decision (per design D2)."""
    from iguanatrader.contexts.risk import engine

    caps = RiskCaps()
    state = _make_state(**state_kwargs)  # type: ignore[arg-type]
    decision = engine.evaluate(_make_proposal("1000"), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == expected
    # state_snapshot mirror is set even on short-circuit reject.
    assert "capital" in decision.state_snapshot


def test_engine_returns_allow_when_all_pass() -> None:
    from iguanatrader.contexts.risk import engine

    caps = RiskCaps()
    state = _make_state()
    decision = engine.evaluate(_make_proposal("1000"), state, caps)
    assert decision.outcome == "allow"
    assert decision.cap_type_breached is None
    assert "capital" in decision.state_snapshot
