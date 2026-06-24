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
    """Generate a synthetic price-ramp history that breaks out on bar ``n - 2``.

    The strategy wrapper slices ``bars[:-1]`` (drops the current bar to enforce
    no-lookahead), so to make the breakout the latest bar that
    ``_compute_signal_impl`` actually sees, the spike must be placed at index
    ``n - 2`` of the full history.
    """
    base = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    for i in range(n):
        # Most bars hover around start_close; bar n-2 pushes high so that
        # after the wrapper drops bars[-1], bars[-1] (==index n-2) is the
        # breakout bar.
        if i == n - 2:
            close = start_close + Decimal("10")
            high = close + Decimal("1")
            low = start_close
        else:
            close = start_close + Decimal(i % 5) * Decimal("0.1")
            high = close + Decimal("0.5")
            low = close - Decimal("0.5")
        bars.append(_bar(t=base + timedelta(days=i), close=close, high=high, low=low))
    return BarHistory(symbol="AAPL", bars=tuple(bars))


def _drop_history(start_close: Decimal = Decimal("100"), n: int = 50) -> BarHistory:
    """Mirror of ``_ramp_history`` that breaks the LOWER channel on bar ``n - 2``.

    After the wrapper drops ``bars[-1]``, the bar at index ``n - 2`` is the
    latest ``_compute_signal_impl`` sees; its close dips well below the prior
    20-bar minimum low → a short (``side == "sell"``) breakout.
    """
    base = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    for i in range(n):
        if i == n - 2:
            close = start_close - Decimal("10")
            high = start_close
            low = close - Decimal("1")
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
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.side == "buy"
    assert proposal.quantity > Decimal("0")
    # Long: stop below entry, target above entry (protective envelope).
    assert proposal.stop_price < proposal.entry_price_indicative
    assert proposal.target_price is not None
    assert proposal.target_price > proposal.entry_price_indicative
    assert proposal.reasoning["direction"] == "long"


def test_donchian_emits_short_on_lower_breakout() -> None:
    strategy = DonchianATRStrategy()
    history = _drop_history()
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.side == "sell"
    assert proposal.quantity > Decimal("0")
    # Short inverts the envelope: stop above entry, target below entry (>0).
    assert proposal.stop_price > proposal.entry_price_indicative
    assert proposal.target_price is not None
    assert Decimal("0") < proposal.target_price < proposal.entry_price_indicative
    assert proposal.reasoning["direction"] == "short"


def test_donchian_quantity_is_whole_shares() -> None:
    """Sizing floors to an integer share count — IBKR rejects bracket/STP
    orders with fractional quantities (and the paper account isn't
    fractional-enabled)."""
    strategy = DonchianATRStrategy()
    proposal = strategy.evaluate(symbol="AAPL", bars=_ramp_history(), config=_config())
    assert proposal is not None
    assert proposal.quantity >= Decimal("1")
    assert proposal.quantity == proposal.quantity.to_integral_value()


def test_donchian_skips_when_risk_budget_below_one_share() -> None:
    """When ``risk_pct * equity`` can't afford even one whole share at this
    stop distance the signal is skipped — flooring to 0 trips the existing
    ``<= 0`` guard rather than forcing 1 share (which would breach the
    ``risk_pct`` envelope)."""
    strategy = DonchianATRStrategy()
    tiny_equity = StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind="donchian_atr",
        symbol="AAPL",
        params={
            "lookback": 20,
            "atr_period": 14,
            "atr_mult": "2.0",
            "risk_pct": "0.01",
            "equity": "1",
        },
        enabled=True,
        version=1,
    )
    proposal = strategy.evaluate(symbol="AAPL", bars=_ramp_history(), config=tiny_equity)
    assert proposal is None


def test_donchian_returns_none_on_flat_history() -> None:
    strategy = DonchianATRStrategy()
    proposal = strategy.evaluate(symbol="AAPL", bars=_flat_history(), config=_config())
    assert proposal is None


def test_donchian_no_signal_when_close_inside_channel() -> None:
    """Regression: no proposal when the latest close sits INSIDE the channel.

    Guards both failure modes of the breakout test: the slice bug where
    ``window_highs`` included ``bars[-1].high`` (long trivially fails) and
    the symmetric always-fire. With the v0.2 bidirectional logic a close
    must break the upper channel (long) OR the lower channel (short); a
    close strictly between ``channel_low`` and ``channel_high`` must yield
    ``None`` on BOTH sides.
    """
    strategy = DonchianATRStrategy()
    base = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    # 48 bars climbing to ~111, then 2 bars whose close (~109.5) lands
    # comfortably between the prior 20-bar low (~107) and high (~112).
    # After the wrapper drops bars[-1], the latest close is inside the
    # channel → neither an upper nor a lower breakout fires.
    for i in range(48):
        close = Decimal("100") + Decimal(i) * Decimal("0.25")
        bars.append(
            _bar(
                t=base + timedelta(days=i),
                close=close,
                high=close + Decimal("0.5"),
                low=close - Decimal("0.5"),
            )
        )
    for i in range(48, 50):
        bars.append(
            _bar(
                t=base + timedelta(days=i),
                close=Decimal("109.5"),
                high=Decimal("110.0"),
                low=Decimal("109.0"),
            )
        )
    history = BarHistory(symbol="AAPL", bars=tuple(bars))
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
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
