"""Per-tenant strategy manager (slice T3).

Reads :class:`StrategyConfig` rows for a tenant, instantiates the
appropriate :class:`Strategy` for each, dispatches ``evaluate`` calls,
aggregates per-strategy :class:`Proposal | None` results.

Hot-reload (FR4): on a `StrategyConfig.version` bump the manager
invalidates its cached instance + rebuilds with new params before the
next evaluate call.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from iguanatrader.contexts.trading.ports import (
    BarHistory,
    Proposal,
    StrategyConfigSnapshot,
)
from iguanatrader.contexts.trading.strategies.bollinger_breakout import (
    BollingerBreakoutStrategy,
)
from iguanatrader.contexts.trading.strategies.donchian_atr import DonchianATRStrategy
from iguanatrader.contexts.trading.strategies.rsi_mean_reversion import (
    RSIMeanReversionStrategy,
)
from iguanatrader.contexts.trading.strategies.sma_cross import SMACrossStrategy

if TYPE_CHECKING:
    from iguanatrader.contexts.trading.strategies.base import Strategy

logger = logging.getLogger(__name__)


#: Strategy-kind dispatch table. Adding a 3rd strategy is a one-line
#: addition here + a new module under ``strategies/``.
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "bollinger_breakout": BollingerBreakoutStrategy,
    "donchian_atr": DonchianATRStrategy,
    "rsi_mean_reversion": RSIMeanReversionStrategy,
    "sma_cross": SMACrossStrategy,
}


class StrategyManager:
    """Builds + caches strategy instances per ``(tenant_id, kind, version)``."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, int], Strategy] = {}

    def evaluate_all(
        self,
        symbol: str,
        bars: BarHistory,
        configs: Iterable[StrategyConfigSnapshot],
    ) -> list[Proposal]:
        """Evaluate every enabled strategy in ``configs``; return non-None proposals.

        ``None`` results are dropped. Default aggregation: union — every
        strategy's signal is independently emitted as a Proposal. The
        service layer (T4) is responsible for downstream dedup +
        risk-engine pre-checks.
        """
        proposals: list[Proposal] = []
        for snapshot in configs:
            if not snapshot.enabled:
                continue
            strategy = self._get_or_build(snapshot)
            if strategy is None:
                logger.warning(
                    "trading.strategy.unknown_kind",
                    extra={"strategy_kind": snapshot.strategy_kind},
                )
                continue
            proposal = strategy.evaluate(symbol=symbol, bars=bars, config=snapshot)
            if proposal is not None:
                proposals.append(proposal)
        return proposals

    def _get_or_build(self, snapshot: StrategyConfigSnapshot) -> Strategy | None:
        cache_key = (snapshot.strategy_kind, snapshot.version)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        cls = STRATEGY_REGISTRY.get(snapshot.strategy_kind)
        if cls is None:
            return None
        instance = cls()
        self._cache[cache_key] = instance
        # Drop stale versions of the same kind (hot-reload).
        for stale_key in list(self._cache):
            if stale_key[0] == snapshot.strategy_kind and stale_key[1] != snapshot.version:
                del self._cache[stale_key]
        return instance


__all__ = ["STRATEGY_REGISTRY", "StrategyManager"]
