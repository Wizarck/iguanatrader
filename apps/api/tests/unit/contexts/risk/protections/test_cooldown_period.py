"""Unit tests for the v1.5 ``cooldown_period`` protection.

Coverage matrix (per ``openspec/changes/risk-cooldown-period/proposal.md``):

* Disabled by default — ``caps.cooldown_seconds is None`` ⇒ always
  ``allow`` regardless of how recent the prior close was.
* No prior close on the proposal's symbol — absent from
  ``state.seconds_since_last_close_by_symbol`` ⇒ ``allow``.
* Within cooldown window — ``seconds_since < cooldown_seconds`` ⇒
  ``reject``, ``cap_type_breached == "cooldown_period"``,
  ``current_pct`` is the elapsed-fraction-of-window ratio.
* At the boundary (exactly equal) — ``seconds_since == cooldown_seconds``
  ⇒ ``allow`` (cooldown is "strictly less than"; wait is satisfied at
  the exact boundary).
* Beyond cooldown — ``seconds_since > cooldown_seconds`` ⇒ ``allow``.
* Per-symbol isolation — SPY in cooldown but proposal targets QQQ ⇒
  ``allow``; the protection MUST key by the proposal's symbol only.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from iguanatrader.contexts.risk.models import (
    RiskCaps,
    RiskState,
    TradeProposalInput,
)
from iguanatrader.contexts.risk.protections import cooldown_period


def _proposal(symbol: str = "SPY") -> TradeProposalInput:
    return TradeProposalInput(
        id=uuid4(),
        tenant_id=uuid4(),
        notional_value=Decimal("1000"),
        side="buy",
        symbol=symbol,
    )


def _state(
    *,
    seconds_by_symbol: dict[str, int] | None = None,
) -> RiskState:
    return RiskState(
        capital=Decimal("100000"),
        seconds_since_last_close_by_symbol=seconds_by_symbol or {},
    )


def test_cooldown_disabled_when_caps_seconds_none() -> None:
    """``cooldown_seconds=None`` (the default) is the kill-switch-off state.

    Even with a fresh close 1 second ago the protection MUST allow —
    we ship default-disabled so existing tenants see no behavioural
    change until they opt in.
    """
    caps = RiskCaps()  # cooldown_seconds default is None.
    state = _state(seconds_by_symbol={"SPY": 1})
    decision = cooldown_period.evaluate(_proposal("SPY"), state, caps)
    assert decision.outcome == "allow"
    assert decision.cap_type_breached is None


def test_cooldown_allows_when_no_prior_close_for_symbol() -> None:
    """A brand-new symbol (absent from the map) cannot be in cooldown.

    The service-layer state builder leaves symbols with zero closed
    trades out of the dict entirely; the protection treats absence as
    "no cooldown applies", not "infinite cooldown".
    """
    caps = RiskCaps(cooldown_seconds=1800)
    state = _state(seconds_by_symbol={})
    decision = cooldown_period.evaluate(_proposal("SPY"), state, caps)
    assert decision.outcome == "allow"
    assert decision.cap_type_breached is None


def test_cooldown_rejects_within_window() -> None:
    """``seconds_since < cooldown_seconds`` ⇒ reject.

    ``current_pct`` reports the elapsed-as-fraction-of-window so
    observability consumers can chart "5 of 30 min through cooldown".
    """
    caps = RiskCaps(cooldown_seconds=1800)
    state = _state(seconds_by_symbol={"SPY": 300})
    decision = cooldown_period.evaluate(_proposal("SPY"), state, caps)
    assert decision.outcome == "reject"
    assert decision.cap_type_breached == "cooldown_period"
    assert decision.current_pct == Decimal("300") / Decimal("1800")


def test_cooldown_allows_at_exact_boundary() -> None:
    """Boundary: ``seconds_since == cooldown_seconds`` ⇒ allow.

    Cooldown is "strictly less than" — at-the-boundary the wait is
    satisfied. Mirrors the per_trade cap's strict-greater-than rejection
    style; operators can reason about the boundary without an off-by-one.
    """
    caps = RiskCaps(cooldown_seconds=1800)
    state = _state(seconds_by_symbol={"SPY": 1800})
    decision = cooldown_period.evaluate(_proposal("SPY"), state, caps)
    assert decision.outcome == "allow"
    assert decision.cap_type_breached is None


def test_cooldown_allows_after_window_elapsed() -> None:
    """``seconds_since > cooldown_seconds`` ⇒ allow."""
    caps = RiskCaps(cooldown_seconds=1800)
    state = _state(seconds_by_symbol={"SPY": 2000})
    decision = cooldown_period.evaluate(_proposal("SPY"), state, caps)
    assert decision.outcome == "allow"
    assert decision.cap_type_breached is None


def test_cooldown_per_symbol_isolation() -> None:
    """SPY in cooldown but proposal targets QQQ ⇒ allow.

    Per-symbol scoping is the whole point — a 30-min cooldown on TSLA
    does not block AAPL signals. The protection MUST key by the
    proposal's symbol; a regression that read "any symbol in cooldown"
    would silently block unrelated trades.
    """
    caps = RiskCaps(cooldown_seconds=1800)
    state = _state(seconds_by_symbol={"SPY": 300})  # SPY mid-cooldown
    decision = cooldown_period.evaluate(_proposal("QQQ"), state, caps)
    assert decision.outcome == "allow"
    assert decision.cap_type_breached is None
