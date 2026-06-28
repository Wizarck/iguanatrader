"""Unit tests for the per-position recommendation scorecard (pure logic).

The verdict is the riskiest piece — rail geometry first (stop/target breaches
dominate), then a horizon-gated "too early" window, then the R-multiple read.
These assert the branch order + R-multiple math for both long and short, and
the fail-soft NO_DATA paths.
"""

from __future__ import annotations

from decimal import Decimal

from iguanatrader.contexts.trading import scorecard


def _card(**kw: object) -> scorecard.Scorecard:
    base: dict[str, object] = {
        "side": "buy",
        "avg_entry": Decimal("100"),
        "stop_price": Decimal("90"),
        "target_price": Decimal("130"),
        "last_price": Decimal("100"),
        "held_market_days": 10,
        "strategy_kind": "donchian_atr",  # horizon 25
    }
    base.update(kw)
    return scorecard.compute(**base)  # type: ignore[arg-type]


def test_no_data_when_avg_missing() -> None:
    c = _card(avg_entry=None)
    assert c.verdict == scorecard.NO_DATA
    assert c.r_multiple is None


def test_no_data_when_last_missing() -> None:
    assert _card(last_price=None).verdict == scorecard.NO_DATA


def test_no_data_when_stop_missing() -> None:
    assert _card(stop_price=None).verdict == scorecard.NO_DATA


def test_r_multiple_and_reward_risk_long() -> None:
    c = _card(last_price=Decimal("106"))
    # move = 106-100 = 6; risk = |100-90| = 10 -> R 0.6
    assert c.r_multiple == Decimal("0.6000")
    # reward = |130-100| = 30 -> reward:risk 3.0
    assert c.reward_risk == Decimal("3.0000")
    # rail_progress = (106-90)/(130-90) = 16/40 = 0.4
    assert c.rail_progress == Decimal("0.4000")


def test_too_early_dominates_when_young_long() -> None:
    # held 2 < 0.33*25 = 8.25 and R not deep red -> TOO_EARLY even at R 0.6
    c = _card(last_price=Decimal("106"), held_market_days=2)
    assert c.verdict == scorecard.TOO_EARLY


def test_on_track_when_mature_and_winning_long() -> None:
    c = _card(last_price=Decimal("106"), held_market_days=10)
    assert c.verdict == scorecard.ON_TRACK


def test_stop_breach_off_track_even_if_young() -> None:
    # rails dominate the horizon gate
    c = _card(last_price=Decimal("89"), held_market_days=1)
    assert c.verdict == scorecard.OFF_TRACK


def test_target_hit_on_track_even_if_young() -> None:
    c = _card(last_price=Decimal("131"), held_market_days=1)
    assert c.verdict == scorecard.ON_TRACK


def test_short_position_r_multiple_and_on_track() -> None:
    # short: entry 100, stop 110, target 70; price falls to 94 -> winning
    c = _card(
        side="sell",
        stop_price=Decimal("110"),
        target_price=Decimal("70"),
        last_price=Decimal("94"),
        held_market_days=10,
    )
    # move = 100-94 = 6; risk = |100-110| = 10 -> R 0.6
    assert c.r_multiple == Decimal("0.6000")
    assert c.verdict == scorecard.ON_TRACK


def test_short_stop_breach_off_track() -> None:
    c = _card(
        side="sell",
        stop_price=Decimal("110"),
        target_price=Decimal("70"),
        last_price=Decimal("111"),  # rose past the stop
        held_market_days=10,
    )
    assert c.verdict == scorecard.OFF_TRACK


def test_unknown_strategy_skips_horizon_gate() -> None:
    # no horizon -> the too-early window cannot fire; a young winner reads the R
    c = _card(last_price=Decimal("106"), held_market_days=2, strategy_kind=None)
    assert c.horizon_days is None
    assert c.verdict == scorecard.ON_TRACK


def test_horizon_labels() -> None:
    assert scorecard.horizon_for("rsi_mean_reversion") == (5, "short")
    assert scorecard.horizon_for("donchian_atr") == (25, "long")
    assert scorecard.horizon_for("unmapped") == (None, None)
    assert scorecard.horizon_for(None) == (None, None)
