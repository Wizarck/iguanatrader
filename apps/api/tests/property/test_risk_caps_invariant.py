"""**CI-blocking** Hypothesis property test for the risk-caps invariant (NFR-R6).

Per slice K1 design D7 + spec ``risk-engine-protections`` Requirement
"Hypothesis property test enforces caps invariant as CI-blocking gate":

For every triple ``(proposal, state, caps)`` the engine considers, IF
``engine.evaluate(...).outcome == "allow"`` THEN every cap (per_trade,
daily_loss, weekly_loss, max_open, max_drawdown) MUST hold. The
property test generates 200 examples; counterexample failures shrink
to minimal failing inputs so debugging is fast.

Markers
-------

* ``@pytest.mark.property`` — picks up the existing
  ``pytest tests/property/`` selector in CI workflows.
* ``@pytest.mark.ci_blocking`` — explicit CI-blocking flag (registered
  in ``pyproject.toml [tool.pytest.ini_options].markers``); reviewers
  can grep for the marker to confirm the gate exists.

Settings
--------

* ``max_examples=200`` — slice-2 convention; pure function so each
  example is microsecond-scale.
* ``deadline=None`` — slice-2 convention; CI runners hiccup, the engine
  itself is fast, total wall-clock <1s typical.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from iguanatrader.contexts.risk import engine
from iguanatrader.contexts.risk.models import (
    RiskCaps,
    RiskState,
    TradeProposalInput,
)

# Pin a stable tenant_id + proposal_id strategy — UUID generation
# itself is not part of the cap invariant; using fixed-seeded UUIDs
# would be a slight test-runtime saving but Hypothesis handles
# arbitrary UUIDs fine.
_uuid_strategy = st.builds(uuid4)

# Decimal strategies bounded so we don't hit Decimal MAX_PREC.
# Capital: positive amount in [1, 1e9].
# Cap percentages: [0, 1) — fractions, not absolute values.
# Drawdown / loss percentages: [0, 1).
# Notional: [0, 1e10) — bigger than capital is allowed (engine should reject).
_capital_strategy = st.decimals(
    min_value=Decimal("1"),
    max_value=Decimal("1000000000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)
_pct_strategy = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("0.99"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)
_notional_strategy = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("10000000000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)
_open_count_strategy = st.integers(min_value=0, max_value=100)


@st.composite
def _caps_strategy(draw: st.DrawFn) -> RiskCaps:
    """Generate arbitrary :class:`RiskCaps` with non-trivial bounds."""
    return RiskCaps(
        per_trade_pct=draw(_pct_strategy),
        daily_loss_pct=draw(_pct_strategy),
        weekly_loss_pct=draw(_pct_strategy),
        max_open_positions=draw(st.integers(min_value=0, max_value=100)),
        max_drawdown_pct=draw(_pct_strategy),
    )


@st.composite
def _state_strategy(draw: st.DrawFn) -> RiskState:
    """Generate arbitrary :class:`RiskState`."""
    return RiskState(
        capital=draw(_capital_strategy),
        day_to_date_loss_pct=draw(_pct_strategy),
        week_to_date_loss_pct=draw(_pct_strategy),
        open_positions_count=draw(_open_count_strategy),
        peak_to_trough_drawdown_pct=draw(_pct_strategy),
    )


@st.composite
def _proposal_strategy(
    draw: st.DrawFn,
    *,
    tenant_id: UUID | None = None,
) -> TradeProposalInput:
    """Generate arbitrary :class:`TradeProposalInput`."""
    return TradeProposalInput(
        id=draw(_uuid_strategy),
        tenant_id=tenant_id or draw(_uuid_strategy),
        notional_value=draw(_notional_strategy),
        side=draw(st.sampled_from(["buy", "sell"])),
    )


@pytest.mark.property
@pytest.mark.ci_blocking
@given(
    proposal=_proposal_strategy(),
    state=_state_strategy(),
    caps=_caps_strategy(),
)
@settings(max_examples=200, deadline=None)
def test_engine_allow_decision_never_breaches_any_cap(
    proposal: TradeProposalInput,
    state: RiskState,
    caps: RiskCaps,
) -> None:
    """The fundamental invariant — every "allow" decision satisfies all caps.

    The engine is a pure function; this test generates 200 arbitrary
    triples and asserts that whenever the decision is ``allow``, every
    cap evaluation must agree. A counterexample (e.g. a future
    refactor that lets a 2.001% per-trade slip through) is the failure
    mode this test is designed to catch.

    Hypothesis shrinks failing inputs to a minimal counterexample —
    the printed example is the smallest ``(proposal, state, caps)``
    that still triggers the violation.
    """
    decision = engine.evaluate(proposal, state, caps)

    if decision.outcome != "allow":
        # Reject path: contract intentionally NOT exhaustive on which
        # cap fired (only that the FIRST one in fixed order did). The
        # invariant is on the allow path; reject correctness is
        # covered by the per-protection unit tests.
        return

    # Per-trade: notional / capital MUST be ≤ per_trade_pct.
    if state.capital > 0:
        per_trade_pct = proposal.notional_value / state.capital
        assert per_trade_pct <= caps.per_trade_pct, (
            f"per_trade breach on allow: notional {proposal.notional_value} / "
            f"capital {state.capital} = {per_trade_pct} > "
            f"caps.per_trade_pct = {caps.per_trade_pct}"
        )
    else:
        # Engine MUST have rejected on zero capital — reaching here is
        # a contract violation.
        pytest.fail(
            f"allow decision at zero capital — proposal {proposal.notional_value}, "
            f"state {state}"
        )

    # Daily / weekly / max_drawdown: state metrics MUST be < cap.
    assert state.day_to_date_loss_pct < caps.daily_loss_pct, (
        f"daily_loss breach on allow: "
        f"day_to_date_loss_pct {state.day_to_date_loss_pct} >= "
        f"caps.daily_loss_pct {caps.daily_loss_pct}"
    )
    assert state.week_to_date_loss_pct < caps.weekly_loss_pct, (
        f"weekly_loss breach on allow: "
        f"week_to_date_loss_pct {state.week_to_date_loss_pct} >= "
        f"caps.weekly_loss_pct {caps.weekly_loss_pct}"
    )
    assert state.peak_to_trough_drawdown_pct < caps.max_drawdown_pct, (
        f"max_drawdown breach on allow: "
        f"peak_to_trough_drawdown_pct {state.peak_to_trough_drawdown_pct} >= "
        f"caps.max_drawdown_pct {caps.max_drawdown_pct}"
    )

    # Max-open: open_positions_count MUST be < max_open_positions.
    assert state.open_positions_count < caps.max_open_positions, (
        f"max_open breach on allow: "
        f"open_positions_count {state.open_positions_count} >= "
        f"caps.max_open_positions {caps.max_open_positions}"
    )


@pytest.mark.property
@pytest.mark.ci_blocking
@given(
    proposal=_proposal_strategy(),
    state=_state_strategy(),
    caps=_caps_strategy(),
)
@settings(max_examples=200, deadline=None)
def test_engine_decision_is_deterministic(
    proposal: TradeProposalInput,
    state: RiskState,
    caps: RiskCaps,
) -> None:
    """Pure function: identical inputs MUST produce identical outputs.

    Sanity-check on top of D1 — if a future refactor accidentally
    introduces a non-deterministic source (e.g. random sampling for
    "soft caps"), this test catches it independently of the
    cap-invariant test above.
    """
    a = engine.evaluate(proposal, state, caps)
    b = engine.evaluate(proposal, state, caps)
    assert a.outcome == b.outcome
    assert a.cap_type_breached == b.cap_type_breached
    assert a.current_pct == b.current_pct
    assert a.state_snapshot == b.state_snapshot
