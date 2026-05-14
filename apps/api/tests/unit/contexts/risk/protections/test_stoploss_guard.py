"""Unit tests for the v1.5 ``stoploss_guard`` protection.

Coverage matrix (per ``openspec/changes/risk-stoploss-guard/proposal.md``):

* Disabled by default — ``caps.stoploss_guard_threshold is None`` ⇒
  always ``allow`` regardless of streak length.
* Threshold not met — ``count < threshold`` ⇒ ``allow``.
* Threshold met (boundary) — ``count == threshold`` ⇒ ``reject``,
  ``cap_type_breached == "stoploss_guard"``, ``current_pct`` is the
  ``count / lookback`` ratio.
* Above threshold — ``count > threshold`` ⇒ ``reject`` (regression
  guard against a strict-greater-than off-by-one).
* Lookback denominator missing (state builder not yet wired) ⇒
  ``current_pct`` is ``None`` rather than dividing by zero.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from iguanatrader.contexts.risk.models import (
    RiskCaps,
    RiskState,
    TradeProposalInput,
)
from iguanatrader.contexts.risk.protections import stoploss_guard


def _proposal() -> TradeProposalInput:
    return TradeProposalInput(
        id=uuid4(),
        tenant_id=uuid4(),
        notional_value=Decimal("1000"),
        side="buy",
    )


def _state(
    *,
    recent_stoploss_count: int = 0,
    recent_lookback: int = 0,
) -> RiskState:
    return RiskState(
        capital=Decimal("100000"),
        recent_stoploss_count_trailing=recent_stoploss_count,
        recent_trades_lookback=recent_lookback,
    )


def test_stoploss_guard_disabled_when_threshold_none() -> None:
    """``threshold=None`` (the default) is the kill-switch-off state.

    Even with a streak of 100 stoplosses the protection MUST allow —
    we ship default-disabled so existing tenants see no behavioural
    change until they opt in via the env var.
    """
    caps = RiskCaps()
    state = _state(recent_stoploss_count=100, recent_lookback=5)
    decision = stoploss_guard.evaluate(_proposal(), state, caps)
    assert decision.outcome == "allow"
    assert decision.cap_type_breached is None


def test_stoploss_guard_allows_below_threshold() -> None:
    """``count < threshold`` ⇒ allow (the streak hasn't built up yet)."""
    caps = RiskCaps(stoploss_guard_threshold=3, stoploss_guard_lookback=5)
    state = _state(recent_stoploss_count=2, recent_lookback=5)
    decision = stoploss_guard.evaluate(_proposal(), state, caps)
    assert decision.outcome == "allow"
    assert decision.cap_type_breached is None


def test_stoploss_guard_rejects_at_threshold_boundary() -> None:
    """``count == threshold`` ⇒ reject (at-or-above semantics).

    Consistent with daily/weekly/max_drawdown: the cap fires the
    moment the threshold is reached, not one trade later.
    """
    caps = RiskCaps(stoploss_guard_threshold=3, stoploss_guard_lookback=5)
    state = _state(recent_stoploss_count=3, recent_lookback=5)
    decision = stoploss_guard.evaluate(_proposal(), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "stoploss_guard"
    # 3 of 5 ⇒ 0.6.
    assert decision.current_pct == Decimal("3") / Decimal("5")


def test_stoploss_guard_rejects_above_threshold() -> None:
    """``count > threshold`` ⇒ reject — regression guard.

    Also verifies that a longer streak (5 of 5) reports the higher
    ratio in ``current_pct`` so observability consumers can chart
    streak severity.
    """
    caps = RiskCaps(stoploss_guard_threshold=3, stoploss_guard_lookback=5)
    state = _state(recent_stoploss_count=5, recent_lookback=5)
    decision = stoploss_guard.evaluate(_proposal(), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "stoploss_guard"
    assert decision.current_pct == Decimal("1")


def test_stoploss_guard_current_pct_none_when_lookback_zero() -> None:
    """Defensive: ``recent_trades_lookback == 0`` ⇒ no divide-by-zero.

    The service-layer state builder is allowed to short-circuit to
    ``lookback=0`` when there are no closed trades to scan yet (or
    when the prerequisite ``exit_reason`` column has not yet been
    backfilled). The protection still has to honour the threshold if
    a caller seeds a non-zero count, but it must NOT compute a
    ratio with a zero denominator.
    """
    caps = RiskCaps(stoploss_guard_threshold=1)
    state = _state(recent_stoploss_count=1, recent_lookback=0)
    decision = stoploss_guard.evaluate(_proposal(), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "stoploss_guard"
    assert decision.current_pct is None
