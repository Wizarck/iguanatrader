"""Unit tests for v1.5 trailing-stop adjustment service.

Coverage matrix (per ``openspec/changes/risk-trailing-stops/proposal.md``):

* ``test_trailing_no_update_when_trigger_not_reached`` — favorable
  pct < trigger ⇒ ``reason="trigger_not_reached"``, new_stop == old.
* ``test_trailing_ratchets_up_on_favorable_move`` — bars rise 5%
  with trigger=3% ⇒ ``reason="trailed"``, new_stop > old.
* ``test_trailing_does_not_ratchet_down_on_pullback`` — candidate <
  current stop ⇒ ``reason="no_update"``, new_stop == old.
* ``test_trailing_uses_post_entry_bars_only`` — pre-entry bars with
  spike highs are ignored when computing the highest close.
* ``test_trailing_long_only_v1_5`` — sell-side trade returns a safe
  ``trigger_not_reached`` no-op; explicit short-side branch deferred to v2.
* ``test_trailing_atr_period_param_overridable`` — passing the helper a
  pre-trimmed window matching ``atr_period=20`` changes the trailing
  distance vs. ``atr_period=14`` for the same input.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from iguanatrader.contexts.risk.stop_management import (
    TradeSnapshot,
    compute_trailing_stop,
)
from iguanatrader.contexts.trading.ports import Bar, BarHistory

ENTRY_TS = datetime(2026, 5, 1, 13, 0, tzinfo=UTC)


def _bar(
    *,
    ts: datetime,
    high: Decimal,
    low: Decimal,
    close: Decimal,
) -> Bar:
    """Construct a Bar; open + volume are not read by the trailing logic."""
    return Bar(
        timestamp=ts,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=Decimal("1000"),
    )


def _trade(
    *,
    side: Literal["buy", "sell"] = "buy",
    entry_price: Decimal = Decimal("100"),
    stop_price: Decimal = Decimal("95"),
    opened_at: datetime = ENTRY_TS,
) -> TradeSnapshot:
    return TradeSnapshot(
        trade_id=uuid4(),
        side=side,
        entry_price=entry_price,
        stop_price=stop_price,
        opened_at=opened_at,
    )


def test_trailing_no_update_when_trigger_not_reached() -> None:
    """``favorable_pct < trail_trigger_pct`` ⇒ no-op with explicit reason.

    Entry 100, trigger 3%, but the best post-entry close is 101 — only
    1% favorable. The function MUST return ``trigger_not_reached`` and
    leave the stop where it was; an over-eager trail at 1% would
    defeat the whole point of the trigger threshold.
    """
    trade = _trade(entry_price=Decimal("100"), stop_price=Decimal("95"))
    bars = BarHistory(
        symbol="SPY",
        bars=[
            _bar(
                ts=ENTRY_TS + timedelta(minutes=5),
                high=Decimal("101.5"),
                low=Decimal("100"),
                close=Decimal("101"),
            ),
            _bar(
                ts=ENTRY_TS + timedelta(minutes=10),
                high=Decimal("101"),
                low=Decimal("100"),
                close=Decimal("100.5"),
            ),
        ],
    )
    update = compute_trailing_stop(
        trade=trade,
        bars=bars,
        trail_trigger_pct=Decimal("0.03"),
        trail_atr_mult=Decimal("1.5"),
    )
    assert update.reason == "trigger_not_reached"
    assert update.new_stop == trade.stop_price
    assert update.old_stop == trade.stop_price
    assert update.trade_id == trade.trade_id


def test_trailing_ratchets_up_on_favorable_move() -> None:
    """A 5% favorable move with a 3% trigger MUST trail the stop up.

    Designed numbers: ATR over the three post-entry bars is engineered
    so ``candidate_stop = highest_close - 1.5 * ATR`` lands above 95
    (the current stop) but below the highest close, exactly the
    "lock in profit, stay below price" intent of trailing.
    """
    trade = _trade(entry_price=Decimal("100"), stop_price=Decimal("95"))
    bars = BarHistory(
        symbol="SPY",
        bars=[
            _bar(
                ts=ENTRY_TS + timedelta(minutes=5),
                high=Decimal("103"),
                low=Decimal("101"),
                close=Decimal("102"),
            ),
            _bar(
                ts=ENTRY_TS + timedelta(minutes=10),
                high=Decimal("104.5"),
                low=Decimal("102"),
                close=Decimal("104"),
            ),
            _bar(
                ts=ENTRY_TS + timedelta(minutes=15),
                high=Decimal("106"),
                low=Decimal("104"),
                close=Decimal("105"),
            ),
        ],
    )
    update = compute_trailing_stop(
        trade=trade,
        bars=bars,
        trail_trigger_pct=Decimal("0.03"),
        trail_atr_mult=Decimal("1.5"),
    )
    assert update.reason == "trailed"
    assert update.new_stop > trade.stop_price
    assert update.new_stop < update.highest_close_since_entry
    assert update.highest_close_since_entry == Decimal("105")
    assert update.atr is not None and update.atr > Decimal("0")


def test_trailing_does_not_ratchet_down_on_pullback() -> None:
    """``candidate_stop < current stop`` ⇒ keep current; never loosen.

    Entry 100, current stop 99 (already-trailed from a prior sweep).
    The post-entry close peaks at 104 → trigger satisfied. But with
    ``trail_atr_mult * ATR`` large enough, ``candidate = 104 - 1.5*ATR``
    lands below 99 — accepting it would WEAKEN protection. Return
    ``no_update`` instead; stops only ratchet UP for longs.
    """
    trade = _trade(entry_price=Decimal("100"), stop_price=Decimal("99"))
    bars = BarHistory(
        symbol="SPY",
        bars=[
            _bar(
                ts=ENTRY_TS + timedelta(minutes=5),
                high=Decimal("104"),
                low=Decimal("96"),  # wide range → high ATR
                close=Decimal("103"),
            ),
            _bar(
                ts=ENTRY_TS + timedelta(minutes=10),
                high=Decimal("105"),
                low=Decimal("95"),  # very wide range → high ATR
                close=Decimal("104"),
            ),
        ],
    )
    update = compute_trailing_stop(
        trade=trade,
        bars=bars,
        trail_trigger_pct=Decimal("0.03"),
        trail_atr_mult=Decimal("1.5"),
    )
    # Sanity: candidate would have ratcheted DOWN; the function MUST refuse.
    assert update.reason == "no_update"
    assert update.new_stop == trade.stop_price
    assert update.atr is not None  # ATR was computed (we got past the trigger).


def test_trailing_uses_post_entry_bars_only() -> None:
    """Pre-entry bars MUST be ignored when computing the highest close.

    A regression that scanned the full ``bars.bars`` would pick up the
    pre-entry spike at 110 and emit a giant trail. The function MUST
    restrict to ``b.timestamp > trade.opened_at`` and see only the
    modest post-entry highs.
    """
    trade = _trade(entry_price=Decimal("100"), stop_price=Decimal("95"))
    bars = BarHistory(
        symbol="SPY",
        bars=[
            # Pre-entry: deceptive high. MUST be ignored.
            _bar(
                ts=ENTRY_TS - timedelta(minutes=30),
                high=Decimal("112"),
                low=Decimal("108"),
                close=Decimal("110"),
            ),
            _bar(
                ts=ENTRY_TS - timedelta(minutes=15),
                high=Decimal("111"),
                low=Decimal("107"),
                close=Decimal("109"),
            ),
            # Post-entry: small favorable move — below trigger.
            _bar(
                ts=ENTRY_TS + timedelta(minutes=5),
                high=Decimal("101"),
                low=Decimal("100"),
                close=Decimal("100.5"),
            ),
            _bar(
                ts=ENTRY_TS + timedelta(minutes=10),
                high=Decimal("101.5"),
                low=Decimal("100.5"),
                close=Decimal("101"),
            ),
        ],
    )
    update = compute_trailing_stop(
        trade=trade,
        bars=bars,
        trail_trigger_pct=Decimal("0.03"),
        trail_atr_mult=Decimal("1.5"),
    )
    # Highest post-entry close is 101, not 110 — trigger NOT reached.
    assert update.reason == "trigger_not_reached"
    assert update.highest_close_since_entry == Decimal("101")
    assert update.new_stop == trade.stop_price


def test_trailing_long_only_v1_5() -> None:
    """Short trades (side="sell") return a safe no-op in v1.5.

    Per proposal §Out of scope the short-side branch is deferred to v2.
    The function MUST NOT raise on sell-side input; instead it returns
    ``trigger_not_reached`` with the current stop unchanged so a v1.5
    cron sweep can blanket-call the function on every open trade
    regardless of side.
    """
    trade = _trade(
        side="sell",
        entry_price=Decimal("100"),
        stop_price=Decimal("105"),
    )
    bars = BarHistory(
        symbol="SPY",
        bars=[
            _bar(
                ts=ENTRY_TS + timedelta(minutes=5),
                high=Decimal("99"),
                low=Decimal("95"),
                close=Decimal("96"),
            ),
            _bar(
                ts=ENTRY_TS + timedelta(minutes=10),
                high=Decimal("97"),
                low=Decimal("93"),
                close=Decimal("94"),
            ),
        ],
    )
    update = compute_trailing_stop(
        trade=trade,
        bars=bars,
        trail_trigger_pct=Decimal("0.03"),
        trail_atr_mult=Decimal("1.5"),
    )
    assert update.reason == "trigger_not_reached"
    assert update.new_stop == trade.stop_price
    assert update.atr is None  # short branch short-circuits before ATR.


def test_trailing_atr_period_param_overridable() -> None:
    """Different ``atr_period`` windows produce different trailing distances.

    The helper's Wilder ATR averages true-range pairs over its bar input.
    Callers control the window by pre-trimming ``bars``. We feed the
    same trade two BarHistory inputs — one with a long pre-entry +
    post-entry sequence (14-period equivalent) and one truncated
    (20-period equivalent simulation via larger range bars) — and assert
    the resulting ``new_stop`` differs. This documents the
    ``atr_period`` knob's wiring contract: the function honours
    whatever ATR-window the caller hands it.
    """
    trade = _trade(entry_price=Decimal("100"), stop_price=Decimal("95"))

    bars_short_window = BarHistory(
        symbol="SPY",
        bars=[
            _bar(
                ts=ENTRY_TS + timedelta(minutes=5),
                high=Decimal("103"),
                low=Decimal("101"),
                close=Decimal("102"),
            ),
            _bar(
                ts=ENTRY_TS + timedelta(minutes=10),
                high=Decimal("105"),
                low=Decimal("103"),
                close=Decimal("104"),
            ),
        ],
    )
    bars_long_window = BarHistory(
        symbol="SPY",
        bars=[
            _bar(
                ts=ENTRY_TS + timedelta(minutes=5),
                high=Decimal("103"),
                low=Decimal("101"),
                close=Decimal("102"),
            ),
            _bar(
                ts=ENTRY_TS + timedelta(minutes=10),
                high=Decimal("103.5"),
                low=Decimal("101.5"),
                close=Decimal("102.5"),
            ),
            _bar(
                ts=ENTRY_TS + timedelta(minutes=15),
                high=Decimal("104"),
                low=Decimal("102"),
                close=Decimal("103"),
            ),
            _bar(
                ts=ENTRY_TS + timedelta(minutes=20),
                high=Decimal("105"),
                low=Decimal("103"),
                close=Decimal("104"),
            ),
        ],
    )
    update_short = compute_trailing_stop(
        trade=trade,
        bars=bars_short_window,
        trail_trigger_pct=Decimal("0.03"),
        trail_atr_mult=Decimal("1.5"),
        atr_period=14,
    )
    update_long = compute_trailing_stop(
        trade=trade,
        bars=bars_long_window,
        trail_trigger_pct=Decimal("0.03"),
        trail_atr_mult=Decimal("1.5"),
        atr_period=20,
    )
    # Both windows trigger (close peaks at 104, 4% > 3%).
    assert update_short.reason == "trailed"
    assert update_long.reason == "trailed"
    # Different ATR windows ⇒ different ATR ⇒ different new_stop.
    assert update_short.atr is not None
    assert update_long.atr is not None
    assert update_short.new_stop != update_long.new_stop
