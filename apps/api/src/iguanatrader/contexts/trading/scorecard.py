"""Per-position recommendation scorecard — pure, read-time, advisory-only.

Turns an open position's stored rails (entry / stop / target), its real average
(fill-weighted or broker avgCost), the latest mark, and how many market days it
has been held into an honest health read the owner can use to judge whether a
recommendation is panning out — WITHOUT fighting the daemon's own mechanical
stop/target exits.

Design (from the SME triage, 2026-06-28):

* The verdict is anchored on **rail geometry**, expressed as an
  **R-multiple** = signed move toward target / initial risk (distance to stop).
  R normalises P&L by each trade's own risk: "-2% with the stop 8% away" (noise)
  is very different from "-2% with the stop 2.5% away" (nearly dead). This is
  noise-resistant and *consistent* with the stop/target the system enforces.
* It is **horizon-gated** so a long-horizon play is not judged OFF-TRACK after a
  few noisy days. Horizon (expected holding period, in market days) is
  OWNER-AUTHORED per strategy — the system cannot infer it. Tune
  :data:`STRATEGY_HORIZON_DAYS` and the threshold constants freely.
* It **never uses the LLM confidence**: that number is uncalibrated (model
  conviction, not P(win)) and absent on most positions. Confidence is surfaced
  separately as a labelled annotation, never folded into the verdict.
* It **fails soft**: any missing input (no fills → no avg, no market-data bar →
  no mark, purged proposal → no stop) yields ``NO_DATA``, never a fake verdict.

Advisory-only: this is a read aid, not an order. It deliberately agrees with the
mechanical rails rather than nudging a manual exit inside the stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# --- Owner-tunable knobs ----------------------------------------------------

#: Expected holding period per ``strategy_kind``, in MARKET (trading) days.
#: Owner-authored — the system has no horizon field and cannot infer one.
#: Mean-reversion exits fast; breakout/trend ride longer. Adjust at will.
STRATEGY_HORIZON_DAYS: dict[str, int] = {
    "rsi_mean_reversion": 5,
    "bollinger_breakout": 12,
    "donchian_atr": 25,
    "volume_donchian": 25,
    "macd_cross": 30,
    "sma_cross": 40,
}

#: ``horizon_days`` at/under this is labelled "short", above it "long".
SHORT_HORIZON_MAX_DAYS: int = 10

#: A position younger than this fraction of its horizon (and not already deep
#: toward its stop) is "too early to tell" — give it rope.
_TOO_EARLY_FRACTION = Decimal("0.33")

#: |R| at/over this is "decided" (toward target = on-track, toward stop = off).
_R_DECIDED = Decimal("0.5")

#: Once the horizon is fully spent, anything under this R is "dead money".
_R_OVERDUE = Decimal("0.25")

# Verdict string constants (stable API surface for the frontend).
ON_TRACK = "on_track"
OFF_TRACK = "off_track"
TOO_EARLY = "too_early"
NO_DATA = "no_data"


def horizon_for(strategy_kind: str | None) -> tuple[int | None, str | None]:
    """Return ``(horizon_days, label)`` for a strategy, or ``(None, None)``.

    ``label`` is ``"short"``/``"long"`` (see :data:`SHORT_HORIZON_MAX_DAYS`).
    Unknown / unmapped strategies get ``(None, None)`` so the verdict runs on
    rail geometry alone (the horizon-gated branches simply do not fire).
    """
    if strategy_kind is None:
        return None, None
    days = STRATEGY_HORIZON_DAYS.get(strategy_kind)
    if days is None:
        return None, None
    label = "short" if days <= SHORT_HORIZON_MAX_DAYS else "long"
    return days, label


@dataclass(frozen=True)
class Scorecard:
    """Computed, advisory health read for one open position."""

    #: P&L in units of initial risk: signed move toward target / |entry-stop|.
    #: Positive = winning, -1 ≈ at the stop, +reward:risk ≈ at the target.
    r_multiple: Decimal | None
    #: Where price sits on the road from stop (0.0) to target (1.0). May exceed
    #: that range once price runs past a rail. ``None`` if target/stop missing.
    rail_progress: Decimal | None
    #: Planned reward:risk = |target-entry| / |entry-stop|. ``None`` if missing.
    reward_risk: Decimal | None
    horizon_days: int | None
    horizon_label: str | None
    #: ``on_track`` | ``off_track`` | ``too_early`` | ``no_data``.
    verdict: str
    #: One human sentence explaining the verdict (English, UI-ready).
    verdict_reason: str


def _q(value: Decimal) -> Decimal:
    """Quantise a display-only ratio to 4 dp."""
    return value.quantize(Decimal("0.0001"))


def compute(
    *,
    side: str,
    avg_entry: Decimal | None,
    stop_price: Decimal | None,
    target_price: Decimal | None,
    last_price: Decimal | None,
    held_market_days: int | None,
    strategy_kind: str | None,
) -> Scorecard:
    """Compute the advisory scorecard for one open position.

    ``side`` is ``"buy"`` (long) or ``"sell"`` (short). All prices are the
    position's real average / stored rails / latest mark. ``held_market_days``
    is the count of trading sessions since the position opened.
    """
    horizon_days, horizon_label = horizon_for(strategy_kind)
    is_long = side == "buy"

    # Fail soft: without an entry, a mark, AND a stop there is no risk frame.
    if avg_entry is None or last_price is None or stop_price is None:
        return Scorecard(
            r_multiple=None,
            rail_progress=None,
            reward_risk=None,
            horizon_days=horizon_days,
            horizon_label=horizon_label,
            verdict=NO_DATA,
            verdict_reason="Not enough data yet (no fills, mark, or stop).",
        )

    risk = abs(avg_entry - stop_price)
    if risk == 0:
        return Scorecard(
            r_multiple=None,
            rail_progress=None,
            reward_risk=None,
            horizon_days=horizon_days,
            horizon_label=horizon_label,
            verdict=NO_DATA,
            verdict_reason="Entry and stop are equal — no risk frame.",
        )

    # Signed profit move toward the trade's goal (side-mirrored).
    move = (last_price - avg_entry) if is_long else (avg_entry - last_price)
    r_multiple = _q(move / risk)

    reward_risk: Decimal | None = None
    rail_progress: Decimal | None = None
    if target_price is not None:
        reward = abs(target_price - avg_entry)
        reward_risk = _q(reward / risk) if risk != 0 else None
        span = abs(target_price - stop_price)
        if span != 0:
            # 0.0 at the stop rail, 1.0 at the target rail.
            from_stop = (last_price - stop_price) if is_long else (stop_price - last_price)
            rail_progress = _q(from_stop / span)

    # --- Verdict (rail geometry first, horizon-gated) -----------------------
    stop_breached = (is_long and last_price <= stop_price) or (
        not is_long and last_price >= stop_price
    )
    target_hit = target_price is not None and (
        (is_long and last_price >= target_price) or (not is_long and last_price <= target_price)
    )

    base = Scorecard(
        r_multiple=r_multiple,
        rail_progress=rail_progress,
        reward_risk=reward_risk,
        horizon_days=horizon_days,
        horizon_label=horizon_label,
        verdict=TOO_EARLY,
        verdict_reason="",
    )

    def out(verdict: str, reason: str) -> Scorecard:
        return Scorecard(
            r_multiple=base.r_multiple,
            rail_progress=base.rail_progress,
            reward_risk=base.reward_risk,
            horizon_days=base.horizon_days,
            horizon_label=base.horizon_label,
            verdict=verdict,
            verdict_reason=reason,
        )

    days_str = "" if held_market_days is None else f"{held_market_days} market day"
    if held_market_days is not None and held_market_days != 1:
        days_str += "s"

    # 0. Hard rails dominate — geometry beats time.
    if stop_breached:
        return out(OFF_TRACK, "Price has reached the stop — exit thesis invalidated.")
    if target_hit:
        return out(ON_TRACK, "Price has reached the target — thesis realised.")

    # 1. Too-early gate — respects the (owner-authored) horizon.
    if (
        horizon_days is not None
        and held_market_days is not None
        and Decimal(held_market_days) < _TOO_EARLY_FRACTION * Decimal(horizon_days)
        and r_multiple > -_R_DECIDED
    ):
        return out(
            TOO_EARLY,
            f"Young: {days_str} of a ~{horizon_days}-day ({horizon_label}) play — "
            "too early to judge.",
        )

    # 2. Mature enough to read the rails.
    if r_multiple >= _R_DECIDED:
        return out(ON_TRACK, f"{r_multiple}R toward the target.")
    if r_multiple <= -_R_DECIDED:
        return out(OFF_TRACK, f"{r_multiple}R toward the stop.")
    if (
        horizon_days is not None
        and held_market_days is not None
        and held_market_days >= horizon_days
        and r_multiple < _R_OVERDUE
    ):
        return out(
            OFF_TRACK,
            f"Horizon spent ({days_str} of ~{horizon_days}) with little progress.",
        )
    return out(TOO_EARLY, f"Still developing ({r_multiple}R) — no clear read yet.")


__all__ = [
    "NO_DATA",
    "OFF_TRACK",
    "ON_TRACK",
    "STRATEGY_HORIZON_DAYS",
    "TOO_EARLY",
    "Scorecard",
    "compute",
    "horizon_for",
]
