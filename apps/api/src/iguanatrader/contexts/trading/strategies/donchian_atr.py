"""Donchian-channel breakout with ATR-based stop sizing (slice T3 MVP).

Long-only entry: ``bars[-1].high >= max(bars[-lookback:].high)``.
Stop: ``entry - atr_mult * ATR(atr_period)``.
Position size: ``risk_pct * equity / (entry - stop)`` (all Decimal).

Default params (overridable via :class:`StrategyConfigSnapshot.params`):

* ``lookback = 20`` (Turtle Traders system 1 minimum).
* ``atr_period = 14``.
* ``atr_mult = 2.0``.
* ``risk_pct = 0.01`` (1% of equity per trade, NFR-R6).
* ``equity = 10000.0`` (default fallback when broker equity not yet
  available; production caller passes the real equity).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from iguanatrader.contexts.trading.ports import (
    BarHistory,
    Proposal,
    StrategyConfigSnapshot,
)
from iguanatrader.contexts.trading.strategies._indicators import compute_atr
from iguanatrader.contexts.trading.strategies.base import Strategy
from iguanatrader.shared.time import now as utc_now

DEFAULT_LOOKBACK: int = 20
DEFAULT_ATR_PERIOD: int = 14
DEFAULT_ATR_MULT: Decimal = Decimal("2.0")
DEFAULT_RISK_PCT: Decimal = Decimal("0.01")
DEFAULT_EQUITY: Decimal = Decimal("10000")


class DonchianATRStrategy(Strategy):
    """Donchian breakout v0 — long-only, ATR-stop, risk-pct sizing."""

    def name(self) -> str:
        return "donchian_atr"

    def version(self) -> str:
        return "0.1.0"

    @property
    def MIN_BARS(self) -> int:  # type: ignore[override]
        # We need at least lookback + atr_period + 1 bars to compute the
        # channel + true-range series; default 35 is the minimum sane.
        return DEFAULT_LOOKBACK + DEFAULT_ATR_PERIOD + 1

    def _compute_signal_impl(
        self,
        symbol: str,
        history: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        params = config.params
        lookback = int(params.get("lookback", DEFAULT_LOOKBACK))
        atr_period = int(params.get("atr_period", DEFAULT_ATR_PERIOD))
        atr_mult = _to_decimal(params.get("atr_mult"), default=DEFAULT_ATR_MULT)
        risk_pct = _to_decimal(params.get("risk_pct"), default=DEFAULT_RISK_PCT)
        equity = _to_decimal(params.get("equity"), default=DEFAULT_EQUITY)

        bars = history.bars
        if len(bars) < lookback + atr_period:
            return None

        latest_close = bars[-1].close
        # Donchian channel: max of the prior `lookback` bars' high (NOT
        # including bars[-1] — already excluded by the wrapper).
        window_highs = [bar.high for bar in bars[-lookback:]]
        channel_high = max(window_highs)

        # Breakout test: today's close >= channel_high.
        if latest_close < channel_high:
            return None

        # ATR(atr_period) over the trailing window — Wilder's smoothing.
        atr = compute_atr(bars[-(atr_period + 1) :])
        if atr is None or atr <= Decimal("0"):
            return None

        entry = latest_close
        stop = entry - atr_mult * atr
        if stop >= entry:
            return None
        risk_per_share = entry - stop
        if risk_per_share <= Decimal("0"):
            return None
        risk_dollars = risk_pct * equity
        quantity = (risk_dollars / risk_per_share).quantize(Decimal("0.0001"))
        if quantity <= Decimal("0"):
            return None

        correlation_id: UUID = uuid4()
        return Proposal(
            tenant_id=config.tenant_id,
            strategy_config_id=config.id,
            symbol=symbol,
            side="buy",
            quantity=quantity,
            entry_price_indicative=entry,
            stop_price=stop,
            confidence_score=None,
            reasoning={
                "strategy": "donchian_atr",
                "lookback": lookback,
                "channel_high": str(channel_high),
                "atr": str(atr),
                "atr_mult": str(atr_mult),
                "risk_pct": str(risk_pct),
                "equity": str(equity),
                "entry": str(entry),
                "stop": str(stop),
                "computed_at": utc_now().isoformat(),
            },
            mode=str(params.get("mode", "paper")),
            correlation_id=correlation_id,
            metadata={"version": self.version()},
        )


def _to_decimal(value: Any, *, default: Decimal) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


__all__ = [
    "DEFAULT_ATR_MULT",
    "DEFAULT_ATR_PERIOD",
    "DEFAULT_LOOKBACK",
    "DEFAULT_RISK_PCT",
    "DonchianATRStrategy",
]
