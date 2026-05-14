"""Trading strategies — slice T3 ``donchian-strategy-mvp``.

Public exports:

* :class:`Strategy` — :class:`StrategyPort`-conforming abstract base.
  Enforces the no-lookahead invariant by slicing the history to
  ``bars[:-1]`` before delegating to the subclass implementation.
* :class:`DonchianATRStrategy` — Donchian-channel breakout with
  ATR-based stop + risk-pct sizing (the MVP strategy).
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
from iguanatrader.contexts.trading.strategies.donchian_atr import DonchianATRStrategy
from iguanatrader.contexts.trading.strategies.manager import StrategyManager
from iguanatrader.contexts.trading.strategies.rsi_mean_reversion import (
    RSIMeanReversionStrategy,
)
from iguanatrader.contexts.trading.strategies.sma_cross import SMACrossStrategy

__all__ = [
    "DonchianATRStrategy",
    "RSIMeanReversionStrategy",
    "SMACrossStrategy",
    "Strategy",
    "StrategyManager",
]
