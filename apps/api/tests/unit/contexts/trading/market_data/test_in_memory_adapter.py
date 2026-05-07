"""Unit tests for :class:`InMemoryMarketDataAdapter` (slice T4-followup-market-data §9.1.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from iguanatrader.contexts.trading.market_data import MarketDataNotAvailableError
from iguanatrader.contexts.trading.market_data.in_memory import (
    InMemoryMarketDataAdapter,
)
from iguanatrader.contexts.trading.ports import Bar


def _make_bar(day: int) -> Bar:
    return Bar(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal(str(100 + day)),
        volume=Decimal("1000000"),
    )


@pytest.mark.asyncio
async def test_seeded_symbol_returns_last_n_bars() -> None:
    seed = {"AAPL": [_make_bar(d) for d in range(50)]}
    adapter = InMemoryMarketDataAdapter(seed=seed)

    history = await adapter.get_bars(
        symbol="AAPL",
        timeframe="1d",
        lookback_bars=10,
    )

    assert history.symbol == "AAPL"
    assert len(history.bars) == 10
    # last 10 → days 40..49
    assert history.bars[0].close == Decimal("140")
    assert history.bars[-1].close == Decimal("149")


@pytest.mark.asyncio
async def test_unseeded_symbol_raises_market_data_not_available() -> None:
    adapter = InMemoryMarketDataAdapter(seed={"AAPL": [_make_bar(0)]})

    with pytest.raises(MarketDataNotAvailableError) as exc_info:
        await adapter.get_bars(symbol="MSFT", timeframe="1d", lookback_bars=10)

    assert "MSFT" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_lookback_greater_than_seed_returns_full_seed() -> None:
    seed = {"AAPL": [_make_bar(d) for d in range(5)]}
    adapter = InMemoryMarketDataAdapter(seed=seed)

    history = await adapter.get_bars(
        symbol="AAPL",
        timeframe="1d",
        lookback_bars=100,
    )

    assert len(history.bars) == 5
    assert history.bars[0].close == Decimal("100")
    assert history.bars[-1].close == Decimal("104")
