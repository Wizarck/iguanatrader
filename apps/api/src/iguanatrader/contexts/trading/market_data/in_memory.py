"""In-memory :class:`MarketDataPort` implementation (test/dev).

Constructor seeds a ``{symbol: list[Bar]}`` map. Used by:

* ``tests/integration/test_trading_pipeline_e2e.py`` (the canonical
  end-to-end integration test).
* Dev workflows where running an IBKR Gateway locally is friction.
* Unit tests for ``bootstrap_routines`` per-symbol propose loops.
"""

from __future__ import annotations

from typing import Literal

from iguanatrader.contexts.trading.market_data import MarketDataNotAvailableError
from iguanatrader.contexts.trading.ports import Bar, BarHistory


class InMemoryMarketDataAdapter:
    """Returns bars from a constructor-seeded dict."""

    def __init__(self, *, seed: dict[str, list[Bar]]) -> None:
        self._seed = seed

    async def get_bars(
        self,
        *,
        symbol: str,
        timeframe: Literal["1d", "1h", "1m"],
        lookback_bars: int,
    ) -> BarHistory:
        """Return the last ``lookback_bars`` bars from the seed.

        Timeframe is ignored — the seed is single-timeframe by design.
        Tests construct one adapter per timeframe under test if needed.
        """
        if symbol not in self._seed:
            raise MarketDataNotAvailableError(
                detail=f"No seeded bars for symbol={symbol!r}",
            )
        bars = self._seed[symbol][-lookback_bars:]
        return BarHistory(symbol=symbol, bars=tuple(bars))


__all__ = ["InMemoryMarketDataAdapter"]
