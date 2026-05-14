"""Trading strategies — slice T3 ``donchian-strategy-mvp``.

Public exports:

* :class:`Strategy` — :class:`StrategyPort`-conforming abstract base.
  Enforces the no-lookahead invariant by slicing the history to
  ``bars[:-1]`` before delegating to the subclass implementation.
* :class:`BollingerBreakoutStrategy` — SMA(20) ± 2-stdev upper-band breakout
  with optional squeeze filter (second v1.5 trend-following strategy;
  volatility-adaptive complement to Donchian).
* :class:`DonchianATRStrategy` — Donchian-channel breakout with
  ATR-based stop + risk-pct sizing (the MVP strategy).
* :class:`MACDCrossStrategy` — Appel 12/26/9 MACD signal-line cross-up
  long-only momentum strategy (third v1.5 addition; complements Donchian
  + SMA cross trend pair).
* :class:`RSIMeanReversionStrategy` — Wilder RSI(14) cross-UP-from-oversold
  long-only counter-trend strategy (first v1.5 counter-trend addition).
* :class:`SMACrossStrategy` — SMA(fast)/SMA(slow) cross sanity-check
  (validates the manager's multi-strategy dispatch).
* :class:`StrategyManager` — per-tenant orchestrator: instantiates
  enabled strategies from :class:`StrategyConfig` rows, dispatches
  ``evaluate`` calls, aggregates :class:`Proposal | None` results.
"""

from __future__ import annotations

from iguanatrader.contexts.trading.strategies.base import Strategy
from iguanatrader.contexts.trading.strategies.bollinger_breakout import (
    BollingerBreakoutStrategy,
)
from iguanatrader.contexts.trading.strategies.donchian_atr import DonchianATRStrategy
from iguanatrader.contexts.trading.strategies.macd_cross import MACDCrossStrategy
from iguanatrader.contexts.trading.strategies.manager import StrategyManager
from iguanatrader.contexts.trading.strategies.rsi_mean_reversion import (
    RSIMeanReversionStrategy,
)
from iguanatrader.contexts.trading.strategies.sma_cross import SMACrossStrategy

__all__ = [
    "BollingerBreakoutStrategy",
    "DonchianATRStrategy",
    "MACDCrossStrategy",
    "RSIMeanReversionStrategy",
    "SMACrossStrategy",
    "Strategy",
    "StrategyManager",
]
