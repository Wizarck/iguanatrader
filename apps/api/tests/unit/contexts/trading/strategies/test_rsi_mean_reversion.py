"""Unit tests for :class:`RSIMeanReversionStrategy` (slice v1.5).

Synthetic-history coverage of the 7 acceptance cases from
``openspec/changes/strategy-rsi-mean-reversion/proposal.md`` §"Tests".
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
from iguanatrader.contexts.trading.strategies.rsi_mean_reversion import (
    DEFAULT_ATR_MULT,
    DEFAULT_EQUITY,
    DEFAULT_RISK_PCT,
    RSIMeanReversionStrategy,
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
        "rsi_period": 14,
        "oversold": "30",
        "atr_period": 14,
        "atr_mult": "2.0",
        "risk_pct": "0.01",
        "equity": "10000",
    }
    params.update(overrides)
    return StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind="rsi_mean_reversion",
        symbol="AAPL",
        params=params,
        enabled=True,
        version=1,
    )


def _cross_up_closes() -> list[Decimal]:
    """Construct a close-series that drops into oversold then rebounds.

    Strategy: 30 bars of steady decline of 1.0 each (so avg_loss
    dominates, RSI heads toward ~0). Then 2 bars of rebound: a small
    positive bar to keep RSI[-2] still below 30, and a large positive bar
    so RSI[-1] crosses back above 30. We append an extra "future" bar at
    the end since the wrapper slices ``bars[:-1]``.
    """
    closes = [Decimal("200")]
    # 30 bars of steady decline.
    for _ in range(30):
        closes.append(closes[-1] - Decimal("1"))
    # rsi_prev: a tiny positive — keeps RSI just under 30.
    closes.append(closes[-1] + Decimal("0.2"))
    # rsi_now: a big rebound — pushes RSI above 30.
    closes.append(closes[-1] + Decimal("8"))
    # Sentinel future bar so the wrapper's bars[:-1] keeps the rebound.
    closes.append(closes[-1] + Decimal("0.1"))
    return closes


def test_rsi_emits_proposal_on_cross_up_from_oversold() -> None:
    strategy = RSIMeanReversionStrategy()
    history = _bars_from_closes(_cross_up_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.side == "buy"
    assert proposal.reasoning["strategy"] == "rsi_mean_reversion"
    rsi_prev = Decimal(proposal.reasoning["rsi_prev"])
    rsi_now = Decimal(proposal.reasoning["rsi_now"])
    oversold = Decimal(proposal.reasoning["oversold"])
    assert rsi_prev < oversold
    assert rsi_now >= oversold


def test_rsi_no_signal_when_not_oversold() -> None:
    strategy = RSIMeanReversionStrategy()
    # Alternating +/- 0.5 around 100 keeps RSI hovering near 50.
    base = Decimal("100")
    closes: list[Decimal] = []
    for i in range(50):
        closes.append(base + (Decimal("0.5") if i % 2 == 0 else Decimal("-0.5")))
    history = _bars_from_closes(closes)
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None


def test_rsi_no_signal_when_still_below_oversold() -> None:
    """RSI[prev] < 30 AND RSI[now] still < 30 → no cross yet → None."""
    strategy = RSIMeanReversionStrategy()
    # Steady decline keeps RSI well below 30 on both prev and now.
    closes = [Decimal("200")]
    for _ in range(50):
        closes.append(closes[-1] - Decimal("1"))
    history = _bars_from_closes(closes)
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None


def test_rsi_no_signal_when_avg_loss_zero() -> None:
    """Strictly rising prices → avg_loss = 0 → RSI = 100 → no signal."""
    strategy = RSIMeanReversionStrategy()
    closes = [Decimal("100")]
    for _ in range(50):
        closes.append(closes[-1] + Decimal("1"))
    history = _bars_from_closes(closes)
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None


def test_rsi_no_signal_when_history_too_short() -> None:
    strategy = RSIMeanReversionStrategy()
    # 5 bars < MIN_BARS (30).
    closes = [Decimal("100") + Decimal(i) for i in range(5)]
    history = _bars_from_closes(closes)
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None


def test_rsi_stop_below_entry() -> None:
    strategy = RSIMeanReversionStrategy()
    history = _bars_from_closes(_cross_up_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.stop_price < proposal.entry_price_indicative


def test_rsi_position_size_respects_risk_pct() -> None:
    """quantity == floor((risk_pct * equity) / (entry - stop)) — whole shares."""
    strategy = RSIMeanReversionStrategy()
    history = _bars_from_closes(_cross_up_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    entry = proposal.entry_price_indicative
    stop = proposal.stop_price
    risk_per_share = entry - stop
    expected = (DEFAULT_RISK_PCT * DEFAULT_EQUITY / risk_per_share).to_integral_value(
        rounding=ROUND_DOWN
    )
    assert proposal.quantity == expected
    # And sanity: stop sits ``atr_mult * atr`` below entry.
    atr = Decimal(proposal.reasoning["atr"])
    assert stop == entry - DEFAULT_ATR_MULT * atr


def test_rsi_quantity_is_whole_shares() -> None:
    """Sizing floors to an integer share count — the fractional sizing bug is fixed."""
    strategy = RSIMeanReversionStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL", bars=_bars_from_closes(_cross_up_closes()), config=_config()
    )
    assert proposal is not None
    assert proposal.quantity >= Decimal("1")
    assert proposal.quantity == proposal.quantity.to_integral_value()


def test_rsi_skips_when_risk_budget_below_one_share() -> None:
    strategy = RSIMeanReversionStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=_bars_from_closes(_cross_up_closes()),
        config=_config(equity="1"),
    )
    assert proposal is None


def test_rsi_cash_sizing_buys_fixed_dollar_amount() -> None:
    strategy = RSIMeanReversionStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=_bars_from_closes(_cross_up_closes()),
        config=_config(sizing_mode="cash", target_cash="1000"),
    )
    assert proposal is not None
    entry = proposal.entry_price_indicative
    expected = (Decimal("1000") / entry).to_integral_value(rounding=ROUND_DOWN)
    assert proposal.quantity == expected
    assert proposal.quantity == proposal.quantity.to_integral_value()
    assert proposal.reasoning["sizing_mode"] == "cash"
    assert proposal.reasoning["target_cash"] == "1000"
