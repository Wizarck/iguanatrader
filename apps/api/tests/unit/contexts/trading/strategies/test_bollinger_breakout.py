"""Unit tests for :class:`BollingerBreakoutStrategy` (slice v1.5).

Synthetic-history coverage of the acceptance cases from
``openspec/changes/strategy-bollinger-breakout/proposal.md`` §"Tests".
The wrapper drops ``bars[-1]`` before delegating, so every constructed
history appends one extra sentinel bar at the end — the "current"
bar used by the strategy is therefore ``bars[-2]`` of the test input.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from iguanatrader.contexts.trading.ports import (
    Bar,
    BarHistory,
    StrategyConfigSnapshot,
)
from iguanatrader.contexts.trading.strategies.bollinger_breakout import (
    DEFAULT_ATR_MULT,
    DEFAULT_EQUITY,
    DEFAULT_RISK_PCT,
    BollingerBreakoutStrategy,
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
        "period": 20,
        "num_std": "2.0",
        "squeeze_threshold": None,
        "squeeze_lookback": 6,
        "atr_period": 14,
        "atr_mult": "2.0",
        "risk_pct": "0.01",
        "equity": "10000",
    }
    params.update(overrides)
    return StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind="bollinger_breakout",
        symbol="AAPL",
        params=params,
        enabled=True,
        version=1,
    )


def _breakout_closes() -> list[Decimal]:
    """Quiet base + a single explosive breakout bar.

    A long stretch of mild oscillation around 100 keeps the SMA(20) near
    100 and the stdev small (~0.5). Then a final breakout to 110 sits
    well above ``sma + 2*stdev``. We append a sentinel "future" bar so the
    wrapper's ``bars[:-1]`` keeps the breakout bar as ``closes[-1]``.
    """
    closes: list[Decimal] = []
    for i in range(40):
        # alternating +/- 0.5 around 100 keeps stdev ~0.5
        closes.append(Decimal("100") + (Decimal("0.5") if i % 2 == 0 else Decimal("-0.5")))
    closes.append(Decimal("110"))  # breakout bar
    closes.append(Decimal("110.1"))  # sentinel future
    return closes


def _flat_closes() -> list[Decimal]:
    """40+ bars of tight oscillation around 100 with no breakout."""
    closes: list[Decimal] = []
    for i in range(40):
        closes.append(Decimal("100") + (Decimal("0.5") if i % 2 == 0 else Decimal("-0.5")))
    closes.append(Decimal("100.4"))  # final bar still inside the band
    closes.append(Decimal("100.5"))  # sentinel
    return closes


def _touch_closes() -> list[Decimal]:
    """Final close sits AT the upper band (touch, not strict cross).

    The strategy uses ``closes[-1] <= upper_band`` → no signal, validating
    the strict-inequality check. We engineer a constant 100.0 history
    (stdev → 0, upper_band → 100.0) and set the final close to 100.0
    exactly — touch without breakout.
    """
    closes: list[Decimal] = []
    for _ in range(40):
        closes.append(Decimal("100"))
    closes.append(Decimal("100"))  # touch — exactly the upper band (stdev=0 → upper=sma)
    closes.append(Decimal("100"))  # sentinel
    return closes


def _wide_bandwidth_breakout_closes() -> list[Decimal]:
    """Wide oscillation prior to a breakout — squeeze filter must block it.

    Alternating ±10 around 100 gives a stdev near 10 → bandwidth ratio
    near 0.4 → far above any sane squeeze threshold (~0.05).
    """
    closes: list[Decimal] = []
    for i in range(40):
        closes.append(Decimal("100") + (Decimal("10") if i % 2 == 0 else Decimal("-10")))
    closes.append(Decimal("140"))  # well above upper band
    closes.append(Decimal("140.1"))  # sentinel
    return closes


def _tight_bandwidth_breakout_closes() -> list[Decimal]:
    """Tightly oscillating prior bars + breakout — squeeze filter must allow it.

    Alternating ±0.1 around 100 → stdev ~0.1 → bandwidth ratio ~0.004 →
    well below a 0.05 squeeze threshold. The final close at 110 is far
    above the upper band.
    """
    closes: list[Decimal] = []
    for i in range(60):
        closes.append(Decimal("100") + (Decimal("0.1") if i % 2 == 0 else Decimal("-0.1")))
    closes.append(Decimal("110"))
    closes.append(Decimal("110.1"))
    return closes


def test_bollinger_emits_proposal_on_breakout_above_upper_band() -> None:
    strategy = BollingerBreakoutStrategy()
    history = _bars_from_closes(_breakout_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.side == "buy"
    assert proposal.reasoning["strategy"] == "bollinger_breakout"
    entry = Decimal(proposal.reasoning["entry"])
    upper_band = Decimal(proposal.reasoning["upper_band"])
    assert entry > upper_band
    assert proposal.reasoning["squeeze_filter_active"] is False


def test_bollinger_no_signal_when_close_within_band() -> None:
    strategy = BollingerBreakoutStrategy()
    history = _bars_from_closes(_flat_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None


def test_bollinger_no_signal_when_close_at_upper_band() -> None:
    """Close exactly equal to upper band must NOT signal (strictly >)."""
    strategy = BollingerBreakoutStrategy()
    history = _bars_from_closes(_touch_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None


def test_bollinger_squeeze_filter_inert_when_disabled() -> None:
    """``squeeze_threshold=None`` + breakout → still fires (filter inert)."""
    strategy = BollingerBreakoutStrategy()
    history = _bars_from_closes(_wide_bandwidth_breakout_closes())
    # Default config has squeeze_threshold=None → filter inert → wide
    # bandwidth is irrelevant; breakout still fires.
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.reasoning["squeeze_filter_active"] is False


def test_bollinger_squeeze_filter_blocks_when_bandwidth_too_wide() -> None:
    """``squeeze_threshold=0.05`` + wide bandwidth prior → no signal."""
    strategy = BollingerBreakoutStrategy()
    history = _bars_from_closes(_wide_bandwidth_breakout_closes())
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=history,
        config=_config(squeeze_threshold="0.05"),
    )
    assert proposal is None


def test_bollinger_squeeze_filter_passes_when_bandwidth_compressed() -> None:
    """``squeeze_threshold=0.05`` + tightly compressed prior bars + breakout → fires."""
    strategy = BollingerBreakoutStrategy()
    history = _bars_from_closes(_tight_bandwidth_breakout_closes())
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=history,
        config=_config(squeeze_threshold="0.05"),
    )
    assert proposal is not None
    assert proposal.reasoning["squeeze_filter_active"] is True


def test_bollinger_stop_below_entry() -> None:
    strategy = BollingerBreakoutStrategy()
    history = _bars_from_closes(_breakout_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.stop_price < proposal.entry_price_indicative


def test_bollinger_position_size_respects_risk_pct() -> None:
    """quantity ≈ (risk_pct * equity) / (entry - stop), quantised to 4 dp."""
    strategy = BollingerBreakoutStrategy()
    history = _bars_from_closes(_breakout_closes())
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    entry = proposal.entry_price_indicative
    stop = proposal.stop_price
    risk_per_share = entry - stop
    expected = (DEFAULT_RISK_PCT * DEFAULT_EQUITY / risk_per_share).quantize(Decimal("0.0001"))
    assert proposal.quantity == expected
    # Sanity: stop = entry - atr_mult * atr.
    atr = Decimal(proposal.reasoning["atr"])
    assert stop == entry - DEFAULT_ATR_MULT * atr


def test_bollinger_no_signal_when_history_too_short() -> None:
    strategy = BollingerBreakoutStrategy()
    # 5 bars << MIN_BARS (36).
    closes = [Decimal("100") + Decimal(i) for i in range(5)]
    history = _bars_from_closes(closes)
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None
