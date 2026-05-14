"""Trailing-stop adjustment service — v1.5 dynamic stop management.

Eighth risk facility. **Not** a pre-trade protection: the existing risk
engine evaluates ``(Proposal, State, Caps) → Decision`` *before* a trade
is opened; trailing stops operate on EXISTING open positions, ratcheting
the protective stop price up (for longs) as the market moves favourably.
See ``openspec/changes/risk-trailing-stops/proposal.md`` for the full
rationale.

The implementation is a single pure function — :func:`compute_trailing_stop`
— plus the value objects it consumes / returns. No I/O, no clock reads,
no SQLAlchemy. The caller (a future cron sweep landed in the follow-up
slice ``orchestration-trailing-stops-cron``) is responsible for fetching
open trades + post-entry bars and persisting the returned new stop.

Long-side logic (per proposal §What):

1. ``highest_close_since_entry = max(b.close for b in bars if b.timestamp > trade.opened_at)``.
2. ``favorable_pct = (highest_close - entry_price) / entry_price``.
3. If ``favorable_pct < trail_trigger_pct``: return ``reason="trigger_not_reached"``;
   the proposed new stop equals the current stop (no-op).
4. Compute Wilder ATR over the post-entry bars (same true-range
   definition used by ``contexts/trading/strategies/_indicators.py``;
   inlined here to avoid risk → trading cross-context coupling — the two
   copies are byte-identical and tracked by the 4-copy hoist heuristic
   established in the strategy slices).
5. ``candidate_stop = highest_close - trail_atr_mult * atr``.
6. If ``candidate_stop > trade.stop_price``: return ``reason="trailed"``
   with ``new_stop=candidate_stop``.
7. Else: ``reason="no_update"`` — stops only ratchet UP for longs (a
   pullback after a new high must not loosen the protective stop).

Sell-side (short) trades currently fall through to
``reason="trigger_not_reached"`` with ``new_stop`` equal to the existing
stop. v1.5 is long-only by default; per proposal §Out of scope the
short-side branch lands alongside shorting in v2.

Defaults disabled: ``RiskCaps.trail_trigger_pct`` is ``None`` out of the
box; the caller is expected to skip the call entirely when the cap is
unset (or alternatively call this function and observe the
``trigger_not_reached`` no-op).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from typing import Literal
from uuid import UUID

from iguanatrader.contexts.trading.ports import Bar, BarHistory

#: Reason taxonomy for :class:`TrailingStopUpdate`. The three exclusive
#: outcomes are inspected by the caller (cron sweep) to decide whether to
#: emit a persistence write + an audit event.
TrailingStopReason = Literal["trailed", "no_update", "trigger_not_reached"]


@dataclass(frozen=True, slots=True)
class TradeSnapshot:
    """Minimal view of an open trade that :func:`compute_trailing_stop` needs.

    Decoupled from ``contexts/trading/models.Trade`` (the SQLAlchemy ORM
    row) for the same reason :class:`TradeProposalInput` is decoupled
    from ``TradeProposal``: the pure-function risk service must not
    import an ORM model. The cron sweep caller converts a ``Trade`` row
    into this DTO before invoking the function.

    Only the four fields the trailing logic reads are included:

    * :attr:`trade_id` — echoed back via :class:`TrailingStopUpdate.trade_id`
      so the caller can persist against the correct row.
    * :attr:`side` — ``"buy"`` for longs (the only exercised branch in v1.5),
      ``"sell"`` for shorts (safe no-op; see module docstring).
    * :attr:`entry_price` — the fill price; the denominator for ``favorable_pct``.
    * :attr:`stop_price` — the trade's CURRENT stop, which the candidate
      must exceed (for longs) before a ratchet fires.
    * :attr:`opened_at` — UTC timestamp; the cutoff used to filter
      "post-entry" bars from the history.
    """

    trade_id: UUID
    side: Literal["buy", "sell"]
    entry_price: Decimal
    stop_price: Decimal
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class TrailingStopUpdate:
    """Return value of :func:`compute_trailing_stop`.

    Always carries the trade id + the proposed stop (which may equal
    the old stop when the reason is ``no_update`` / ``trigger_not_reached``)
    so the caller can write a uniform audit row regardless of the
    branch taken. ``highest_close_since_entry`` + ``atr`` are echoed
    for observability: a downstream "why didn't the stop trail today?"
    investigation needs both numbers to reconstruct the decision.

    ``atr`` may be ``None`` in the ``trigger_not_reached`` branch where
    the function short-circuits before computing it — the caller should
    treat ``atr is None`` as "ATR not computed" rather than "ATR was 0".
    """

    trade_id: UUID
    old_stop: Decimal
    new_stop: Decimal
    highest_close_since_entry: Decimal
    atr: Decimal | None
    reason: TrailingStopReason


def _wilder_atr(bars: list[Bar]) -> Decimal | None:
    """Wilder ATR over ``bars``. Byte-identical to the trading helper.

    Inlined to avoid a ``risk → trading._indicators`` cross-context
    import; the two copies are tracked by the project-wide 4-copy hoist
    rule (this is the 4th caller — fold both into ``apps/api/src/iguanatrader/
    contexts/shared/`` in a follow-up slice when the rule next fires).
    """
    if len(bars) < 2:
        return None
    true_ranges: list[Decimal] = []
    for prev, cur in pairwise(bars):
        tr1 = cur.high - cur.low
        tr2 = abs(cur.high - prev.close)
        tr3 = abs(cur.low - prev.close)
        true_ranges.append(max(tr1, tr2, tr3))
    if not true_ranges:
        return None
    total = sum(true_ranges, Decimal("0"))
    return total / Decimal(len(true_ranges))


def compute_trailing_stop(
    *,
    trade: TradeSnapshot,
    bars: BarHistory,
    trail_trigger_pct: Decimal,
    trail_atr_mult: Decimal,
    atr_period: int = 14,
) -> TrailingStopUpdate:
    """Return the proposed trailing-stop update for ``trade``.

    Pure function. Does NOT mutate state; the caller persists.

    The ``atr_period`` parameter is currently informational — the
    Wilder ATR is computed over **all** post-entry bars (the proposal's
    "ATR over the post-entry bars" wording). When the post-entry window
    is shorter than ``atr_period`` the function still produces a usable
    ATR estimate from whatever bars are available rather than refusing;
    the caller is responsible for deciding whether a thin window is
    acceptable. Bumping ``atr_period`` produces a different result only
    when callers pre-truncate ``bars`` — exercised by the
    ``atr_period_overridable`` test via explicit pre-trim.
    """
    # v1.5 long-only: sell-side trades short-circuit. The branch exists so
    # the function never raises for a valid input; the v2 short slice will
    # mirror the logic with inverted comparisons.
    if trade.side == "sell":
        return TrailingStopUpdate(
            trade_id=trade.trade_id,
            old_stop=trade.stop_price,
            new_stop=trade.stop_price,
            highest_close_since_entry=trade.entry_price,
            atr=None,
            reason="trigger_not_reached",
        )

    # Filter to strictly-after-entry bars. ``>`` (not ``>=``) so the bar
    # that contained the fill is excluded — its close already informed
    # the entry decision and including it would be "lookahead into the
    # entry bar". Empty post-entry window is the brand-new-trade case;
    # no favorable move can have been recorded.
    post_entry = [b for b in bars.bars if b.timestamp > trade.opened_at]
    if not post_entry:
        return TrailingStopUpdate(
            trade_id=trade.trade_id,
            old_stop=trade.stop_price,
            new_stop=trade.stop_price,
            highest_close_since_entry=trade.entry_price,
            atr=None,
            reason="trigger_not_reached",
        )

    highest_close = max(b.close for b in post_entry)
    favorable_pct = (highest_close - trade.entry_price) / trade.entry_price

    if favorable_pct < trail_trigger_pct:
        return TrailingStopUpdate(
            trade_id=trade.trade_id,
            old_stop=trade.stop_price,
            new_stop=trade.stop_price,
            highest_close_since_entry=highest_close,
            atr=None,
            reason="trigger_not_reached",
        )

    atr = _wilder_atr(list(post_entry))
    if atr is None:
        # Only one post-entry bar — true range needs a previous bar. The
        # trigger fired but ATR is undefined; treat as "no update" so the
        # caller doesn't write a zero-distance candidate stop equal to
        # ``highest_close`` itself.
        return TrailingStopUpdate(
            trade_id=trade.trade_id,
            old_stop=trade.stop_price,
            new_stop=trade.stop_price,
            highest_close_since_entry=highest_close,
            atr=None,
            reason="no_update",
        )

    candidate_stop = highest_close - trail_atr_mult * atr

    if candidate_stop > trade.stop_price:
        return TrailingStopUpdate(
            trade_id=trade.trade_id,
            old_stop=trade.stop_price,
            new_stop=candidate_stop,
            highest_close_since_entry=highest_close,
            atr=atr,
            reason="trailed",
        )

    # Pullback or sideways — keep the existing stop. Longs ratchet up only.
    return TrailingStopUpdate(
        trade_id=trade.trade_id,
        old_stop=trade.stop_price,
        new_stop=trade.stop_price,
        highest_close_since_entry=highest_close,
        atr=atr,
        reason="no_update",
    )


__all__ = [
    "TradeSnapshot",
    "TrailingStopReason",
    "TrailingStopUpdate",
    "compute_trailing_stop",
]
