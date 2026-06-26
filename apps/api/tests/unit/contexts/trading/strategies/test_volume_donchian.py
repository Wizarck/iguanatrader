"""Unit tests for :class:`VolumeDonchianStrategy` (slice v1.5).

Synthetic-history coverage of the 8 acceptance cases from
``openspec/changes/strategy-volume-donchian/proposal.md`` §"Tests".

The wrapper drops ``bars[-1]`` before delegating, so every constructed
history appends one extra sentinel bar at the end — the "current" bar
used by the strategy is therefore ``bars[-2]`` of the test input. The
breakout/volume gate is engineered to land on that current bar.
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
from iguanatrader.contexts.trading.strategies.volume_donchian import (
    DEFAULT_ATR_MULT,
    DEFAULT_EQUITY,
    DEFAULT_RISK_PCT,
    DEFAULT_TARGET_MULT,
    VolumeDonchianStrategy,
)


def _bar(
    *,
    t: datetime,
    close: Decimal,
    high: Decimal,
    low: Decimal,
    volume: Decimal,
) -> Bar:
    return Bar(
        timestamp=t,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _bars(
    closes: list[Decimal],
    volumes: list[Decimal],
    *,
    high_offset: Decimal = Decimal("0.5"),
    low_offset: Decimal = Decimal("0.5"),
) -> BarHistory:
    """Synthesise a :class:`BarHistory` from co-indexed closes + volumes."""
    assert len(closes) == len(volumes), "closes/volumes length mismatch"
    base = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    for i, (c, v) in enumerate(zip(closes, volumes, strict=True)):
        bars.append(
            _bar(
                t=base + timedelta(days=i),
                close=c,
                high=c + high_offset,
                low=c - low_offset,
                volume=v,
            )
        )
    return BarHistory(symbol="AAPL", bars=tuple(bars))


def _config(**overrides: object) -> StrategyConfigSnapshot:
    params: dict[str, object] = {
        "period": 20,
        "vol_window": 20,
        "volume_threshold": "1.5",
        "atr_period": 14,
        "atr_mult": "2.0",
        "risk_pct": "0.01",
        "equity": "10000",
    }
    params.update(overrides)
    return StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind="volume_donchian",
        symbol="AAPL",
        params=params,
        enabled=True,
        version=1,
    )


def _breakout_with_volume(
    *,
    volume_multiplier: Decimal,
    n_prior: int = 40,
) -> BarHistory:
    """Quiet base + a strict channel-break bar carrying ``volume_multiplier``x
    the trailing-average volume. A sentinel future bar follows so the
    wrapper truncation leaves the breakout bar as ``bars[-1]``.
    """
    base_close = Decimal("100")
    base_volume = Decimal("1000")
    closes: list[Decimal] = []
    volumes: list[Decimal] = []
    for i in range(n_prior):
        # Alternating closes around 100 → channel high (max of prior
        # highs) sits at 100.5 (since each high = close + 0.5).
        closes.append(base_close + (Decimal("0.5") if i % 2 == 0 else Decimal("-0.5")))
        volumes.append(base_volume)
    # Breakout bar: close above the prior channel high (max of prior
    # bars' highs = 101 since high = close + 0.5 and the highest prior
    # close = 100.5 → highest prior high = 101).
    closes.append(Decimal("110"))
    volumes.append(base_volume * volume_multiplier)
    # Sentinel future bar — wrapper drops this.
    closes.append(Decimal("110.1"))
    volumes.append(base_volume)
    return _bars(closes, volumes)


def _flat_history(n: int = 42) -> BarHistory:
    """Flat closes + flat volumes — no breakout, no volume anomaly."""
    closes = [Decimal("100")] * n
    volumes = [Decimal("1000")] * n
    return _bars(closes, volumes)


def test_volume_donchian_emits_on_breakout_with_volume() -> None:
    strategy = VolumeDonchianStrategy()
    history = _breakout_with_volume(volume_multiplier=Decimal("2.0"))
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.side == "buy"
    assert proposal.reasoning["strategy"] == "volume_donchian"
    current_close = Decimal(proposal.reasoning["current_close"])
    donchian_high = Decimal(proposal.reasoning["donchian_high"])
    assert current_close > donchian_high
    volume_ratio = Decimal(proposal.reasoning["volume_ratio"])
    assert volume_ratio >= Decimal("1.5")


def test_volume_donchian_no_signal_when_volume_insufficient() -> None:
    """Channel break BUT current volume == trailing avg (ratio 1.0) → None."""
    strategy = VolumeDonchianStrategy()
    history = _breakout_with_volume(volume_multiplier=Decimal("1.0"))
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None


def test_volume_donchian_no_signal_when_no_breakout() -> None:
    strategy = VolumeDonchianStrategy()
    proposal = strategy.evaluate(symbol="AAPL", bars=_flat_history(), config=_config())
    assert proposal is None


def test_volume_donchian_threshold_param_overridable() -> None:
    """volume_threshold=2.0 rejects a 1.5x volume that would pass at default."""
    strategy = VolumeDonchianStrategy()
    history = _breakout_with_volume(volume_multiplier=Decimal("1.5"))
    # Sanity at default threshold (1.5x): the same history fires.
    baseline = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert baseline is not None
    # Override to 2.0x - the 1.5x volume is now insufficient -> no signal.
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=history,
        config=_config(volume_threshold="2.0"),
    )
    assert proposal is None


def test_volume_donchian_no_signal_when_history_too_short() -> None:
    strategy = VolumeDonchianStrategy()
    # 5 bars << MIN_BARS (36).
    closes = [Decimal("100") + Decimal(i) for i in range(5)]
    volumes = [Decimal("1000")] * 5
    history = _bars(closes, volumes)
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is None


def test_volume_donchian_stop_below_entry() -> None:
    strategy = VolumeDonchianStrategy()
    history = _breakout_with_volume(volume_multiplier=Decimal("2.0"))
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.stop_price < proposal.entry_price_indicative


def test_volume_donchian_target_above_entry_atr_based() -> None:
    """Bracket-complete (WS-C): target = entry + target_mult x ATR, above entry."""
    strategy = VolumeDonchianStrategy()
    history = _breakout_with_volume(volume_multiplier=Decimal("2.0"))
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    entry = proposal.entry_price_indicative
    atr = Decimal(proposal.reasoning["atr"])
    assert proposal.target_price is not None
    assert proposal.target_price == entry + DEFAULT_TARGET_MULT * atr
    assert proposal.stop_price < entry < proposal.target_price
    assert proposal.reasoning["target"] == str(proposal.target_price)
    assert proposal.reasoning["target_mult"] == str(DEFAULT_TARGET_MULT)


def test_volume_donchian_rejects_nonpositive_target_mult() -> None:
    """WS-C review: target_mult=0 → long target == entry → inverted bracket → None."""
    strategy = VolumeDonchianStrategy()
    history = _breakout_with_volume(volume_multiplier=Decimal("2.0"))
    assert strategy.evaluate(symbol="AAPL", bars=history, config=_config(target_mult="0")) is None


def test_volume_donchian_position_size_respects_risk_pct() -> None:
    """quantity == floor((risk_pct * equity) / (entry - stop)) — whole shares."""
    strategy = VolumeDonchianStrategy()
    history = _breakout_with_volume(volume_multiplier=Decimal("2.0"))
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    entry = proposal.entry_price_indicative
    stop = proposal.stop_price
    risk_per_share = entry - stop
    expected = (DEFAULT_RISK_PCT * DEFAULT_EQUITY / risk_per_share).to_integral_value(
        rounding=ROUND_DOWN
    )
    assert proposal.quantity == expected
    # Sanity: stop = entry - atr_mult * atr.
    atr = Decimal(proposal.reasoning["atr"])
    assert stop == entry - DEFAULT_ATR_MULT * atr


def test_volume_donchian_quantity_is_whole_shares() -> None:
    """Sizing floors to an integer share count — the fractional sizing bug is fixed."""
    strategy = VolumeDonchianStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=_breakout_with_volume(volume_multiplier=Decimal("2.0")),
        config=_config(),
    )
    assert proposal is not None
    assert proposal.quantity >= Decimal("1")
    assert proposal.quantity == proposal.quantity.to_integral_value()


def test_volume_donchian_skips_when_risk_budget_below_one_share() -> None:
    strategy = VolumeDonchianStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=_breakout_with_volume(volume_multiplier=Decimal("2.0")),
        config=_config(equity="1"),
    )
    assert proposal is None


def test_volume_donchian_cash_sizing_buys_fixed_dollar_amount() -> None:
    strategy = VolumeDonchianStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=_breakout_with_volume(volume_multiplier=Decimal("2.0")),
        config=_config(sizing_mode="cash", target_cash="1000"),
    )
    assert proposal is not None
    entry = proposal.entry_price_indicative
    expected = (Decimal("1000") / entry).to_integral_value(rounding=ROUND_DOWN)
    assert proposal.quantity == expected
    assert proposal.quantity == proposal.quantity.to_integral_value()
    assert proposal.reasoning["sizing_mode"] == "cash"
    assert proposal.reasoning["target_cash"] == "1000"


def test_volume_donchian_reasoning_includes_volume_ratio() -> None:
    strategy = VolumeDonchianStrategy()
    history = _breakout_with_volume(volume_multiplier=Decimal("2.0"))
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    # Required reasoning keys per proposal §"Reasoning dict shape".
    for key in (
        "donchian_high",
        "current_close",
        "current_volume",
        "avg_volume",
        "volume_ratio",
        "volume_threshold",
    ):
        assert key in proposal.reasoning
        # Each is a Decimal-as-string.
        Decimal(proposal.reasoning[key])
    # Ratio sanity: 2x input -> ratio == 2.
    assert Decimal(proposal.reasoning["volume_ratio"]) == Decimal("2")
