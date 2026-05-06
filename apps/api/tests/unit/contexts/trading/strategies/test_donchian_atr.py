"""Unit tests for :class:`DonchianATRStrategy` (slice T3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from iguanatrader.contexts.trading.ports import (
    Bar,
    BarHistory,
    StrategyConfigSnapshot,
)
from iguanatrader.contexts.trading.strategies.donchian_atr import DonchianATRStrategy


def _bar(*, t: datetime, close: Decimal, high: Decimal, low: Decimal) -> Bar:
    return Bar(
        timestamp=t,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=Decimal("1000"),
    )


def _ramp_history(start_close: Decimal = Decimal("100"), n: int = 50) -> BarHistory:
    """Generate a synthetic price-ramp history that BREAKS OUT on the last bar."""
    base = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    for i in range(n):
        # Most bars hover around start_close; final bar pushes high.
        if i == n - 1:
            close = start_close + Decimal("10")
            high = close + Decimal("1")
            low = start_close
        else:
            close = start_close + Decimal(i % 5) * Decimal("0.1")
            high = close + Decimal("0.5")
            low = close - Decimal("0.5")
        bars.append(_bar(t=base + timedelta(days=i), close=close, high=high, low=low))
    return BarHistory(symbol="AAPL", bars=tuple(bars))


def _flat_history(n: int = 50) -> BarHistory:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    for i in range(n):
        bars.append(
            _bar(
                t=base + timedelta(days=i),
                close=Decimal("100"),
                high=Decimal("100.5"),
                low=Decimal("99.5"),
            )
        )
    return BarHistory(symbol="AAPL", bars=tuple(bars))


def _config() -> StrategyConfigSnapshot:
    return StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind="donchian_atr",
        symbol="AAPL",
        params={"lookback": 20, "atr_period": 14, "atr_mult": "2.0", "risk_pct": "0.01"},
        enabled=True,
        version=1,
    )


def test_donchian_emits_proposal_on_breakout() -> None:
    strategy = DonchianATRStrategy()
    history = _ramp_history()
    # The wrapper drops the breakout bar — the truncated history may NOT
    # have a breakout. Generate a history where the breakout is on bar
    # n-2 so after wrapper truncation the latest bar is the breakout.
    # The wrapper slices bars[:-1], so we need the n-2 bar to be the
    # breakout: replicate by adding one more flat bar after the ramp.
    extra_bar = _bar(
        t=history.bars[-1].timestamp + timedelta(days=1),
        close=Decimal("100"),
        high=Decimal("100.5"),
        low=Decimal("99.5"),
    )
    bars = [*history.bars, extra_bar]
    history_with_extra = BarHistory(symbol="AAPL", bars=tuple(bars))
    proposal = strategy.evaluate(symbol="AAPL", bars=history_with_extra, config=_config())
    assert proposal is not None
    assert proposal.side == "buy"
    assert proposal.quantity > Decimal("0")
    assert proposal.stop_price < proposal.entry_price_indicative


def test_donchian_returns_none_on_flat_history() -> None:
    strategy = DonchianATRStrategy()
    proposal = strategy.evaluate(symbol="AAPL", bars=_flat_history(), config=_config())
    assert proposal is None


def test_donchian_short_history_returns_none() -> None:
    strategy = DonchianATRStrategy()
    short = BarHistory(symbol="AAPL", bars=tuple(_flat_history().bars[:5]))
    proposal = strategy.evaluate(symbol="AAPL", bars=short, config=_config())
    assert proposal is None


def test_donchian_name_and_version_constants() -> None:
    strategy = DonchianATRStrategy()
    assert strategy.name() == "donchian_atr"
    assert strategy.version().startswith("0.")
