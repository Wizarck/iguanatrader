"""Unit tests for :class:`MACDCrossStrategy` (slice v1.5).

Synthetic-history coverage of the 8 acceptance cases from
``openspec/changes/strategy-macd-cross/proposal.md`` §"Tests".

Each engineered close-series carries an extra "sentinel future" bar at
the end so the wrapper's ``bars[:-1]`` truncation keeps the intended
"now" bar as ``closes[-2]`` of the test input.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from uuid import uuid4

from iguanatrader.contexts.trading.ports import (
    Bar,
    BarHistory,
    StrategyConfigSnapshot,
)
from iguanatrader.contexts.trading.strategies.macd_cross import (
    DEFAULT_ATR_MULT,
    DEFAULT_EQUITY,
    DEFAULT_RISK_PCT,
    DEFAULT_TARGET_MULT,
    MACDCrossStrategy,
)


def _bar(*, t: datetime, close: Decimal, high: Decimal, low: Decimal) -> Bar:
    return Bar(
        timestamp=t,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=Decimal("1000"),
    )


def _bars_from_closes(closes: list[Decimal]) -> BarHistory:
    """Synthesise a :class:`BarHistory` where each bar has high=close+0.5, low=close-0.5."""
    base = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    for i, c in enumerate(closes):
        bars.append(
            _bar(
                t=base + timedelta(days=i),
                close=c,
                high=c + Decimal("0.5"),
                low=c - Decimal("0.5"),
            )
        )
    return BarHistory(symbol="AAPL", bars=tuple(bars))


def _config(**overrides: object) -> StrategyConfigSnapshot:
    params: dict[str, object] = {
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "bias_filter": None,
        "atr_period": 14,
        "atr_mult": "2.0",
        "risk_pct": "0.01",
        "equity": "10000",
    }
    params.update(overrides)
    return StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind="macd_cross",
        symbol="AAPL",
        params=params,
        enabled=True,
        version=1,
    )


def _negative_cross_closes() -> list[Decimal]:
    """Engineered cross-up where ``macd_now < 0`` at the cross.

    30 flat bars to seed the EMAs (total ``>=`` MIN_BARS after wrapper
    truncation), then 20 bars of monotonic decline (drives MACD strongly
    negative), then one explosive +15 pop. The explosive pop lifts the
    MACD line through the signal line at the last bar — but MACD is still
    negative because the slow EMA has not yet caught up. Verified offline:
    ``macd_prev=-4.51, macd_now=-3.41, signal_prev=-3.67, signal_now=-3.61``.
    """
    closes: list[Decimal] = [Decimal("200")] * 30
    for _ in range(20):
        closes.append(closes[-1] - Decimal("1"))
    closes.append(closes[-1] + Decimal("15"))  # the cross-up bar (still macd<0)
    closes.append(closes[-1] + Decimal("0.01"))  # sentinel
    return closes


def _positive_cross_closes() -> list[Decimal]:
    """Engineered cross-up where ``macd_now > 0`` at the cross.

    5-bar plateau seed, then 35 bars of monotonic +1 uptrend (MACD goes
    strongly positive), then 12 bars of monotonic -1 dip (drives MACD
    back below its signal line), then 9 bars of monotonic +1 recovery —
    the 9th recovery bar is where the cross-up fires. Verified offline:
    ``macd_prev=1.33, macd_now=1.55, signal_prev=1.41, signal_now=1.44``.
    """
    closes: list[Decimal] = [Decimal("100")] * 5
    for _ in range(35):
        closes.append(closes[-1] + Decimal("1"))
    for _ in range(12):
        closes.append(closes[-1] - Decimal("1"))
    for _ in range(9):
        closes.append(closes[-1] + Decimal("1"))
    closes.append(closes[-1] + Decimal("0.01"))  # sentinel
    return closes


def _flat_closes() -> list[Decimal]:
    """60+ bars of tight oscillation around 100 — no momentum shift."""
    closes: list[Decimal] = []
    for i in range(60):
        closes.append(Decimal("100") + (Decimal("0.5") if i % 2 == 0 else Decimal("-0.5")))
    closes.append(Decimal("100"))  # sentinel
    return closes


def _cross_down_closes() -> list[Decimal]:
    """Mirror of the positive-cross series — produces a cross-DOWN at the last bar.

    5-bar plateau seed, then 35 bars of -1 monotonic downtrend (MACD
    deeply negative), then 12 bars of +1 bounce (MACD rises above
    signal), then 9 bars of -1 resumption — the 9th resumption bar
    produces the mirror cross-DOWN (``macd_now < signal_now`` while
    ``macd_prev >= signal_prev``). Strategy is long-only, so this must
    return ``None``.
    """
    closes: list[Decimal] = [Decimal("200")] * 5
    for _ in range(35):
        closes.append(closes[-1] - Decimal("1"))
    for _ in range(12):
        closes.append(closes[-1] + Decimal("1"))
    for _ in range(9):
        closes.append(closes[-1] - Decimal("1"))
    closes.append(closes[-1] - Decimal("0.01"))  # sentinel
    return closes


def test_macd_emits_proposal_on_cross_up() -> None:
    strategy = MACDCrossStrategy()
    history = _bars_from_closes(_positive_cross_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.side == "buy"
    assert proposal.reasoning["strategy"] == "macd_cross"
    macd_prev = Decimal(proposal.reasoning["macd_prev"])
    macd_now = Decimal(proposal.reasoning["macd_now"])
    signal_prev = Decimal(proposal.reasoning["signal_prev"])
    signal_now = Decimal(proposal.reasoning["signal_now"])
    assert macd_prev <= signal_prev
    assert macd_now > signal_now


def test_macd_no_signal_when_no_cross() -> None:
    strategy = MACDCrossStrategy()
    history = _bars_from_closes(_flat_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None


def test_macd_no_signal_when_cross_down() -> None:
    """Mirror series produces a cross-DOWN — long-only must return None."""
    strategy = MACDCrossStrategy()
    history = _bars_from_closes(_cross_down_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None


def test_macd_bias_filter_blocks_negative_cross() -> None:
    """``bias_filter='positive'`` + cross with ``macd_now < 0`` → None."""
    strategy = MACDCrossStrategy()
    history = _bars_from_closes(_negative_cross_closes())
    # Sanity: with the filter OFF the same history fires.
    baseline = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert baseline is not None
    assert Decimal(baseline.reasoning["macd_now"]) < Decimal("0")
    # With the filter ON the negative MACD blocks the entry.
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=history,
        config=_config(bias_filter="positive"),
    )
    assert proposal is None


def test_macd_bias_filter_allows_positive_cross() -> None:
    """``bias_filter='positive'`` + cross with ``macd_now > 0`` → fires."""
    strategy = MACDCrossStrategy()
    history = _bars_from_closes(_positive_cross_closes())
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=history,
        config=_config(bias_filter="positive"),
    )
    assert proposal is not None
    assert proposal.reasoning["bias_filter"] == "positive"
    assert Decimal(proposal.reasoning["macd_now"]) > Decimal("0")


def test_macd_no_signal_when_history_too_short() -> None:
    strategy = MACDCrossStrategy()
    # 5 bars << MIN_BARS (51).
    closes = [Decimal("100") + Decimal(i) for i in range(5)]
    history = _bars_from_closes(closes)
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None


def test_macd_stop_below_entry() -> None:
    strategy = MACDCrossStrategy()
    history = _bars_from_closes(_positive_cross_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.stop_price < proposal.entry_price_indicative


def test_macd_target_above_entry_atr_based() -> None:
    """Bracket-complete (WS-C): target = entry + target_mult x ATR, above entry."""
    strategy = MACDCrossStrategy()
    history = _bars_from_closes(_positive_cross_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    entry = proposal.entry_price_indicative
    atr = Decimal(proposal.reasoning["atr"])
    assert proposal.target_price is not None
    assert proposal.target_price == entry + DEFAULT_TARGET_MULT * atr
    assert proposal.stop_price < entry < proposal.target_price
    assert proposal.reasoning["target"] == str(proposal.target_price)
    assert proposal.reasoning["target_mult"] == str(DEFAULT_TARGET_MULT)


def test_macd_rejects_nonpositive_target_mult() -> None:
    """WS-C review: target_mult=0 → long target == entry → inverted bracket → None."""
    strategy = MACDCrossStrategy()
    history = _bars_from_closes(_positive_cross_closes())
    assert strategy.evaluate(symbol="AAPL", bars=history, config=_config(target_mult="0")) is None


def test_macd_position_size_respects_risk_pct() -> None:
    """quantity == floor((risk_pct * equity) / (entry - stop)) — whole shares."""
    strategy = MACDCrossStrategy()
    history = _bars_from_closes(_positive_cross_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    entry = proposal.entry_price_indicative
    stop = proposal.stop_price
    risk_per_share = entry - stop
    expected = (DEFAULT_RISK_PCT * DEFAULT_EQUITY / risk_per_share).to_integral_value(
        rounding=ROUND_DOWN
    )
    assert proposal.quantity == expected
    # Sanity: stop sits ``atr_mult * atr`` below entry.
    atr = Decimal(proposal.reasoning["atr"])
    assert stop == entry - DEFAULT_ATR_MULT * atr


def test_macd_quantity_is_whole_shares() -> None:
    """Sizing floors to an integer share count — the fractional sizing bug is fixed."""
    strategy = MACDCrossStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL", bars=_bars_from_closes(_positive_cross_closes()), config=_config()
    )
    assert proposal is not None
    assert proposal.quantity >= Decimal("1")
    assert proposal.quantity == proposal.quantity.to_integral_value()


def test_macd_skips_when_risk_budget_below_one_share() -> None:
    strategy = MACDCrossStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=_bars_from_closes(_positive_cross_closes()),
        config=_config(equity="1"),
    )
    assert proposal is None


def test_macd_cash_sizing_buys_fixed_dollar_amount() -> None:
    strategy = MACDCrossStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=_bars_from_closes(_positive_cross_closes()),
        config=_config(sizing_mode="cash", target_cash="1000"),
    )
    assert proposal is not None
    entry = proposal.entry_price_indicative
    expected = (Decimal("1000") / entry).to_integral_value(rounding=ROUND_DOWN)
    assert proposal.quantity == expected
    assert proposal.quantity == proposal.quantity.to_integral_value()
    assert proposal.reasoning["sizing_mode"] == "cash"
    assert proposal.reasoning["target_cash"] == "1000"
