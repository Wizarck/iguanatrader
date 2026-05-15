"""Forward-roll bar simulator with configurable exit policy.

Pure function — no I/O, no DB. The caller loads bars + proposal + an
ATR estimate (for the target trigger) and gets back a
:class:`SimulatedOutcome`.

Exit-trigger priority (when multiple fire on the same bar):

1. **stop** — wins if low (buy) / high (sell) breaches the active
   stop. The trailing variant may have ratcheted the stop forward
   over earlier bars.
2. **target** — only consulted when ``policy.use_target=True`` AND
   the same-bar high (buy) / low (sell) reaches the target.
3. **horizon** — if the bar timestamp exceeds opened_at +
   horizon_days, exit at that bar's ``open`` (mark-to-market).

Tied stop+target on the same bar: stop wins (conservative — assume
the worse fill happened first intrabar). This matches the
common-practice in backtest libraries (Backtrader / Lumibot
defaults).

Long-only v1.5: the function handles both ``side="buy"`` and
``side="sell"`` symmetrically so the eventual v2 short slice doesn't
need changes here.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from iguanatrader.contexts.replay.models import ExitPolicy, SimulatedOutcome
from iguanatrader.contexts.risk.stop_management import (
    TradeSnapshot,
    compute_trailing_stop,
)
from iguanatrader.contexts.trading.ports import Bar, BarHistory

if TYPE_CHECKING:
    from datetime import datetime


def _compute_atr_at_entry(pre_entry_bars: Sequence[Bar], atr_period: int = 14) -> Decimal | None:
    """Wilder ATR over the last ``atr_period`` pre-entry bars.

    Returns ``None`` if there are fewer than 2 bars (cannot compute a
    range). Matches the shape used by :func:`compute_trailing_stop`
    so the target-trigger ATR is comparable to the trailing-stop ATR.
    """
    if len(pre_entry_bars) < 2:
        return None
    window = list(pre_entry_bars[-(atr_period + 1) :])
    true_ranges: list[Decimal] = []
    for i in range(1, len(window)):
        prev_close = window[i - 1].close
        high = window[i].high
        low = window[i].low
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)
    if not true_ranges:
        return None
    return sum(true_ranges, Decimal("0")) / Decimal(len(true_ranges))


def _exit_outcome(
    *,
    proposal_id: UUID,
    policy_name: str,
    side: str,
    entry_price: Decimal,
    quantity: Decimal,
    exit_price: Decimal,
    exit_at: datetime,
    bars_held: int,
    reason: str,
) -> SimulatedOutcome:
    """Build a SimulatedOutcome with PnL signed correctly per side."""
    if side == "buy":
        pnl_abs = (exit_price - entry_price) * quantity
        pnl_pct = (exit_price - entry_price) / entry_price if entry_price != 0 else Decimal("0")
    else:
        pnl_abs = (entry_price - exit_price) * quantity
        pnl_pct = (entry_price - exit_price) / entry_price if entry_price != 0 else Decimal("0")
    return SimulatedOutcome(
        proposal_id=proposal_id,
        policy_name=policy_name,
        exited=True,
        exit_reason=reason,
        exit_price=exit_price,
        exit_at=exit_at,
        bars_held=bars_held,
        pnl_absolute=pnl_abs,
        pnl_pct=pnl_pct,
    )


def simulate_pnl(
    *,
    proposal_id: UUID,
    side: str,
    entry_price: Decimal,
    initial_stop: Decimal,
    quantity: Decimal,
    opened_at: datetime,
    pre_entry_bars: Sequence[Bar],
    post_entry_bars: Sequence[Bar],
    policy: ExitPolicy,
) -> SimulatedOutcome:
    """Forward-roll ``post_entry_bars``; return the simulated outcome."""
    if not post_entry_bars:
        return SimulatedOutcome(
            proposal_id=proposal_id,
            policy_name=policy.name,
            exited=False,
            exit_reason="no_bars",
            exit_price=entry_price,
            exit_at=None,
            bars_held=0,
            pnl_absolute=Decimal("0"),
            pnl_pct=Decimal("0"),
        )

    horizon_end = opened_at + timedelta(days=policy.horizon_days)
    active_stop = initial_stop

    # Compute target up-front (uses pre-entry ATR estimate).
    target: Decimal | None = None
    if policy.use_target:
        atr = _compute_atr_at_entry(pre_entry_bars, atr_period=policy.trail_atr_period)
        if atr is not None and atr > 0:
            if side == "buy":
                target = entry_price + policy.target_atr_multiplier * atr
            else:
                target = entry_price - policy.target_atr_multiplier * atr

    bars_held = 0
    for bar in post_entry_bars:
        bars_held += 1

        # Horizon expiry — exit at this bar's open (mark-to-market).
        if bar.timestamp > horizon_end:
            return _exit_outcome(
                proposal_id=proposal_id,
                policy_name=policy.name,
                side=side,
                entry_price=entry_price,
                quantity=quantity,
                exit_price=bar.open,
                exit_at=bar.timestamp,
                bars_held=bars_held,
                reason="horizon",
            )

        # Trailing ratchet — recompute the active stop from a synthetic
        # TradeSnapshot. compute_trailing_stop uses ALL post-entry bars
        # for ATR + the highest-close-since-entry; we pass the slice up
        # to (and including) the current bar.
        if policy.use_trailing_stop and side == "buy":
            snapshot = TradeSnapshot(
                trade_id=proposal_id,  # the function uses it for logging only
                side="buy",
                entry_price=entry_price,
                stop_price=active_stop,
                opened_at=opened_at,
            )
            history_slice = BarHistory(
                symbol="",
                bars=tuple(post_entry_bars[:bars_held]),
            )
            update = compute_trailing_stop(
                trade=snapshot,
                bars=history_slice,
                trail_trigger_pct=policy.trail_trigger_pct,
                trail_atr_mult=policy.trail_atr_mult,
                atr_period=policy.trail_atr_period,
            )
            if update.reason == "trailed":
                active_stop = update.new_stop

        # Stop check — buy: low breaches; sell: high breaches.
        if side == "buy" and bar.low <= active_stop:
            return _exit_outcome(
                proposal_id=proposal_id,
                policy_name=policy.name,
                side=side,
                entry_price=entry_price,
                quantity=quantity,
                exit_price=active_stop,
                exit_at=bar.timestamp,
                bars_held=bars_held,
                reason="stop",
            )
        if side == "sell" and bar.high >= active_stop:
            return _exit_outcome(
                proposal_id=proposal_id,
                policy_name=policy.name,
                side=side,
                entry_price=entry_price,
                quantity=quantity,
                exit_price=active_stop,
                exit_at=bar.timestamp,
                bars_held=bars_held,
                reason="stop",
            )

        # Target check — buy: high reaches; sell: low reaches. Stop
        # wins on the same bar (already checked above).
        if target is not None:
            if side == "buy" and bar.high >= target:
                return _exit_outcome(
                    proposal_id=proposal_id,
                    policy_name=policy.name,
                    side=side,
                    entry_price=entry_price,
                    quantity=quantity,
                    exit_price=target,
                    exit_at=bar.timestamp,
                    bars_held=bars_held,
                    reason="target",
                )
            if side == "sell" and bar.low <= target:
                return _exit_outcome(
                    proposal_id=proposal_id,
                    policy_name=policy.name,
                    side=side,
                    entry_price=entry_price,
                    quantity=quantity,
                    exit_price=target,
                    exit_at=bar.timestamp,
                    bars_held=bars_held,
                    reason="target",
                )

    # Ran out of bars before any trigger fired — exit at last close
    # (mark-to-market). Distinct from "horizon" because the operator
    # may want to filter these in the report (data ran short).
    last = post_entry_bars[-1]
    return _exit_outcome(
        proposal_id=proposal_id,
        policy_name=policy.name,
        side=side,
        entry_price=entry_price,
        quantity=quantity,
        exit_price=last.close,
        exit_at=last.timestamp,
        bars_held=bars_held,
        reason="no_exit",
    )


__all__ = ["simulate_pnl"]
