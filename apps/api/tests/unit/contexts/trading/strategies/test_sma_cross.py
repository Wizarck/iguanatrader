"""Unit tests for :class:`SMACrossStrategy` — sizing-change + signal coverage.

Closes the WS-A gap: sma_cross had no dedicated test file, so its
fractional→integer sizing change (and the new cash mode) were otherwise only
exercised opportunistically by the registry-wide property harness.
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
from iguanatrader.contexts.trading.strategies.sma_cross import (
    DEFAULT_TARGET_RR,
    SMACrossStrategy,
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


def _golden_cross_closes() -> list[Decimal]:
    """200 flat bars at 100 then a single rise to 105, plus a dropped sentinel.

    During the flat run SMA(fast)==SMA(slow)==100 (prev fast <= prev slow). The
    105 bar lifts SMA(50) above SMA(200) → a cross-up on the bar the wrapper
    keeps as bars[-1]. The stdev of returns over the vol window is positive (one
    5% jump), so the volatility-based sizing is well-defined.
    """
    closes = [Decimal("100")] * 200
    closes.append(Decimal("105"))  # the cross-up bar
    closes.append(Decimal("105.1"))  # sentinel — wrapper drops bars[-1]
    return closes


def _config(**overrides: object) -> StrategyConfigSnapshot:
    params: dict[str, object] = {
        "fast": 50,
        "slow": 200,
        "vol_window": 20,
        "risk_pct": "0.01",
        "equity": "10000",
    }
    params.update(overrides)
    return StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind="sma_cross",
        symbol="AAPL",
        params=params,
        enabled=True,
        version=1,
    )


def test_sma_cross_emits_on_golden_cross() -> None:
    strategy = SMACrossStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL", bars=_bars_from_closes(_golden_cross_closes()), config=_config()
    )
    assert proposal is not None
    assert proposal.side == "buy"
    assert proposal.reasoning["strategy"] == "sma_cross"
    assert proposal.stop_price < proposal.entry_price_indicative


def test_sma_cross_no_signal_on_flat_history() -> None:
    strategy = SMACrossStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL", bars=_bars_from_closes([Decimal("100")] * 205), config=_config()
    )
    assert proposal is None


def test_sma_cross_target_is_reward_risk_multiple() -> None:
    """Bracket-complete (WS-C): no ATR, so target = entry + target_rr x stop-distance."""
    strategy = SMACrossStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL", bars=_bars_from_closes(_golden_cross_closes()), config=_config()
    )
    assert proposal is not None
    entry = proposal.entry_price_indicative
    stop = proposal.stop_price
    assert proposal.target_price is not None
    assert proposal.target_price == entry + DEFAULT_TARGET_RR * (entry - stop)
    assert stop < entry < proposal.target_price
    assert proposal.reasoning["target"] == str(proposal.target_price)
    assert proposal.reasoning["target_rr"] == str(DEFAULT_TARGET_RR)


def test_sma_cross_quantity_is_whole_shares() -> None:
    """Sizing floors to an integer share count — the fractional .quantize(0.0001)
    bug (which IBKR would reject) is fixed via the shared sizing helper."""
    strategy = SMACrossStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL", bars=_bars_from_closes(_golden_cross_closes()), config=_config()
    )
    assert proposal is not None
    assert proposal.quantity >= Decimal("1")
    assert proposal.quantity == proposal.quantity.to_integral_value()


def test_sma_cross_skips_when_risk_budget_below_one_share() -> None:
    strategy = SMACrossStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=_bars_from_closes(_golden_cross_closes()),
        config=_config(equity="1"),
    )
    assert proposal is None


def test_sma_cross_cash_sizing_buys_fixed_dollar_amount() -> None:
    strategy = SMACrossStrategy()
    proposal = strategy.evaluate(
        symbol="AAPL",
        bars=_bars_from_closes(_golden_cross_closes()),
        config=_config(sizing_mode="cash", target_cash="1000"),
    )
    assert proposal is not None
    entry = proposal.entry_price_indicative
    expected = (Decimal("1000") / entry).to_integral_value(rounding=ROUND_DOWN)
    assert proposal.quantity == expected
    assert proposal.quantity == proposal.quantity.to_integral_value()
    assert proposal.reasoning["sizing_mode"] == "cash"
    assert proposal.reasoning["target_cash"] == "1000"
