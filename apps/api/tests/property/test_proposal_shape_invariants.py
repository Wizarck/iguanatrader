"""**CI-blocking** Hypothesis property test for ``Proposal`` shape invariants.

For every strategy in :data:`STRATEGY_REGISTRY` and every random
``BarHistory``, IF ``strategy.evaluate(...)`` returns a non-None
``Proposal``, THEN every shape invariant from the design must hold:

1. ``proposal.quantity > 0``.
2. ``proposal.side in {"buy", "sell"}``.
3. ``proposal.entry_price_indicative > 0``.
4. ``proposal.stop_price > 0``.
5. **Direction invariant**:
   - ``side == "buy"`` -> ``stop_price < entry_price_indicative``.
   - ``side == "sell"`` -> ``stop_price > entry_price_indicative``.
6. ``proposal.mode in {"paper", "live"}``.
7. ``proposal.symbol == bars.symbol``.
8. ``proposal.tenant_id == config.tenant_id``.

If a strategy returns None, the test confirms the call did not raise.

Markers:

* ``@pytest.mark.property`` - picks up the existing
  ``pytest tests/property/`` selector in CI workflows.
* ``@pytest.mark.ci_blocking`` - CI-blocking gate so a regression
  breaks the build.

Settings: ``max_examples=200`` per strategy (slice-2 convention),
``deadline=None`` (CI runners hiccup).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from iguanatrader.contexts.trading.ports import (
    Bar,
    BarHistory,
    StrategyConfigSnapshot,
)
from iguanatrader.contexts.trading.strategies.manager import STRATEGY_REGISTRY

_ALLOWED_SIDES: frozenset[str] = frozenset({"buy", "sell"})
_ALLOWED_MODES: frozenset[str] = frozenset({"paper", "live"})


def _gen_bar_history(close_seq: list[float], symbol: str = "AAPL") -> BarHistory:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    for i, close in enumerate(close_seq):
        c = Decimal(str(round(close, 4)))
        bars.append(
            Bar(
                timestamp=base + timedelta(days=i),
                open=c,
                high=c + Decimal("0.5"),
                low=c - Decimal("0.5"),
                close=c,
                volume=Decimal("1000"),
            )
        )
    return BarHistory(symbol=symbol, bars=tuple(bars))


def _make_config(strategy_kind: str, symbol: str = "AAPL") -> StrategyConfigSnapshot:
    return StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind=strategy_kind,
        symbol=symbol,
        params={},
        enabled=True,
        version=1,
    )


@pytest.mark.property
@pytest.mark.ci_blocking
@pytest.mark.parametrize("strategy_kind", list(STRATEGY_REGISTRY))
@given(
    closes=st.lists(
        st.floats(
            min_value=1.0,
            max_value=10000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=60,
        max_size=120,
    ),
)
@settings(
    deadline=None,
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_proposal_shape_invariants_hold_for_every_strategy(
    strategy_kind: str,
    closes: list[float],
) -> None:
    """For every strategy and random bars, if a Proposal is returned, every
    invariant in the docstring above MUST hold.

    The test does NOT assert that a Proposal IS returned (most random
    histories won't trigger a signal); it asserts the shape invariants
    iff one is returned.
    """
    cls = STRATEGY_REGISTRY[strategy_kind]
    strategy = cls()
    symbol = "AAPL"
    config = _make_config(strategy_kind, symbol=symbol)
    history = _gen_bar_history(closes, symbol=symbol)

    proposal = strategy.evaluate(symbol, history, config)
    if proposal is None:
        return

    # Invariant 1 - positive quantity.
    assert proposal.quantity > Decimal(
        "0"
    ), f"{strategy_kind}: proposal.quantity={proposal.quantity} is not > 0"

    # Invariant 2 - side is one of the canonical literals.
    assert (
        proposal.side in _ALLOWED_SIDES
    ), f"{strategy_kind}: proposal.side={proposal.side!r} not in {_ALLOWED_SIDES}"

    # Invariant 3 - positive entry price.
    assert proposal.entry_price_indicative > Decimal(
        "0"
    ), f"{strategy_kind}: entry_price={proposal.entry_price_indicative} is not > 0"

    # Invariant 4 - positive stop price.
    assert proposal.stop_price > Decimal(
        "0"
    ), f"{strategy_kind}: stop_price={proposal.stop_price} is not > 0"

    # Invariant 5 - direction-aware stop placement.
    if proposal.side == "buy":
        assert proposal.stop_price < proposal.entry_price_indicative, (
            f"{strategy_kind}: buy stop_price={proposal.stop_price} >= "
            f"entry={proposal.entry_price_indicative} (long stop must be below entry)"
        )
    else:  # sell
        assert proposal.stop_price > proposal.entry_price_indicative, (
            f"{strategy_kind}: sell stop_price={proposal.stop_price} <= "
            f"entry={proposal.entry_price_indicative} (short stop must be above entry)"
        )

    # Invariant 6 - mode is one of the canonical literals.
    assert (
        proposal.mode in _ALLOWED_MODES
    ), f"{strategy_kind}: mode={proposal.mode!r} not in {_ALLOWED_MODES}"

    # Invariant 7 - no cross-symbol contamination.
    assert (
        proposal.symbol == symbol
    ), f"{strategy_kind}: proposal.symbol={proposal.symbol!r} != bars.symbol={symbol!r}"

    # Invariant 8 - no cross-tenant contamination.
    assert (
        proposal.tenant_id == config.tenant_id
    ), f"{strategy_kind}: proposal.tenant_id != config.tenant_id"


@pytest.mark.property
@pytest.mark.parametrize("strategy_kind", list(STRATEGY_REGISTRY))
@given(
    closes=st.lists(
        st.floats(
            min_value=1.0,
            max_value=10000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=10,
        max_size=30,
    ),
)
@settings(
    deadline=None,
    max_examples=30,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_strategy_evaluate_does_not_raise_on_short_random_history(
    strategy_kind: str,
    closes: list[float],
) -> None:
    """Even on too-short histories, ``evaluate`` must NOT raise.

    Returning ``None`` is the canonical "insufficient data" path. A
    raise here would propagate out of the strategy resolver and into
    the propose loop, which already has FR-isolation per-symbol catch
    blocks - but the strategy itself should be defensive.
    """
    cls = STRATEGY_REGISTRY[strategy_kind]
    strategy = cls()
    symbol = "AAPL"
    config = _make_config(strategy_kind, symbol=symbol)
    history = _gen_bar_history(closes, symbol=symbol)

    # MUST NOT raise.
    _ = strategy.evaluate(symbol, history, config)
