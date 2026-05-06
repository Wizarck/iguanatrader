"""Abstract :class:`Strategy` base — no-lookahead-enforcing wrapper (slice T3).

Per design: subclasses implement only ``_compute_signal_impl(history)``
where ``history`` is **already truncated** to exclude the current bar.
The wrapper :meth:`evaluate` slices ``bars`` to ``bars[:-1]`` before
delegating, so subclasses physically cannot peek at the future no
matter how they try. Property-based test in
``tests/property/test_strategy_no_lookahead.py`` certifies the
invariant on every CI run.

NFR-R5 reliability invariant. The wrapper is fast — slicing a tuple
or list is O(1) for the slice object — and adds zero per-bar cost.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from decimal import Decimal

from iguanatrader.contexts.trading.ports import (
    BarHistory,
    Proposal,
    StrategyConfigSnapshot,
)

logger = logging.getLogger(__name__)


class Strategy(ABC):
    """Abstract :class:`StrategyPort`-conforming base with no-lookahead guard.

    Subclasses MUST implement:

    * :meth:`name` — strategy kind identifier matching
      :attr:`StrategyConfig.strategy_kind`.
    * :meth:`version` — semver string matching
      :attr:`StrategyConfig.version`.
    * :meth:`_compute_signal_impl` — sees only ``bars[:-1]``.

    Subclasses MUST NOT override :meth:`evaluate` — that's the
    invariant-enforcing wrapper.
    """

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def _compute_signal_impl(
        self,
        symbol: str,
        history: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        """Compute the signal from ``history`` (already truncated to bars[:-1]).

        Subclass body. The wrapper has already validated history length +
        absence of NaN gaps. Returning ``None`` means "no signal".
        """
        ...

    # ------------------------------------------------------------------
    # Wrapper (final)
    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        bars: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        """:class:`StrategyPort` entry point — enforces no-lookahead.

        Slices ``bars.bars`` to drop the current bar (``bars[:-1]``), runs
        :meth:`_validate_history`, and delegates to
        :meth:`_compute_signal_impl` only if validation passes. Returns
        ``None`` short-circuit when validation fails (insufficient bars,
        NaN, or gap), emitting structlog narration.
        """
        truncated = BarHistory(symbol=bars.symbol, bars=tuple(bars.bars[:-1]))
        if not self._validate_history(truncated):
            logger.info(
                "trading.strategy.no_signal",
                extra={
                    "strategy": self.name(),
                    "symbol": symbol,
                    "reason": "history_validation_failed",
                    "bars_seen": len(truncated.bars),
                },
            )
            return None

        proposal = self._compute_signal_impl(symbol, truncated, config)
        if proposal is None:
            logger.info(
                "trading.strategy.no_signal",
                extra={
                    "strategy": self.name(),
                    "symbol": symbol,
                    "reason": "no_signal_from_impl",
                },
            )
            return None

        logger.info(
            "trading.strategy.evaluated",
            extra={
                "strategy": self.name(),
                "symbol": symbol,
                "version": self.version(),
                "side": proposal.side,
                "quantity": str(proposal.quantity),
            },
        )
        return proposal

    # ------------------------------------------------------------------
    # Validation helper (subclasses may extend)
    # ------------------------------------------------------------------

    MIN_BARS: int = 1

    def _validate_history(self, history: BarHistory) -> bool:
        """Return True iff ``history`` is dense + non-NaN + ≥ ``MIN_BARS``."""
        if len(history.bars) < self.MIN_BARS:
            return False
        for bar in history.bars:
            for value in (bar.open, bar.high, bar.low, bar.close, bar.volume):
                if not isinstance(value, Decimal):
                    return False
                if value.is_nan() or not math.isfinite(float(value)):
                    return False
        return True


__all__ = ["Strategy"]
