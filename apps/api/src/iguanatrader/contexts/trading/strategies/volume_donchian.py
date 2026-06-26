"""Donchian-channel breakout with volume-anomaly confirmation gate (v1.5).

Fourth and final v1.5 strategy. Long-only entry combines two checks:

1. **Donchian channel break** — same shape as
   :class:`DonchianATRStrategy`: ``closes[-1] > max(high[i]
   for i in range(-period-1, -1))`` — strict break above the prior
   ``period`` bars' high (current bar excluded from the channel).
2. **Volume gate** — ``volume[-1] >= volume_threshold *
   mean(volume[-vol_window-1:-1])`` — current bar's volume must
   exceed the trailing average by the configured ratio. The trailing
   average **excludes** the current bar; otherwise the ratio would
   be tautological.

Stop sized off ``ATR(atr_period)`` (shared helper); quantity from
``risk_pct * equity / (entry - stop)`` matching the rest of the
registry. Per ADR-008 the vanilla :class:`DonchianATRStrategy` and
this volume-confirmed variant can coexist on different symbols
simultaneously; the risk engine handles dedup downstream.

Default params (overridable via :class:`StrategyConfigSnapshot.params`):

* ``period = 20`` (Donchian canonical default).
* ``vol_window = 20`` (trailing volume-average window).
* ``volume_threshold = 1.5`` (conservative — ~30-50% fewer signals
  than vanilla Donchian per typical backtests).
* ``atr_period = 14``.
* ``atr_mult = 2.0`` (protective stop distance, in ATRs).
* ``target_mult = 3.0`` (take-profit distance, in ATRs).
* ``risk_pct = 0.01`` (NFR-R6).
* ``equity = 10000`` (default fallback when broker equity not yet
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
from iguanatrader.contexts.trading.strategies._indicators import _compute_atr
from iguanatrader.contexts.trading.strategies.base import Strategy
from iguanatrader.contexts.trading.strategies.sizing import (
    SIZING_MODE_RISK,
    calculate_quantity,
)
from iguanatrader.shared.time import now as utc_now

DEFAULT_PERIOD: int = 20
DEFAULT_VOL_WINDOW: int = 20
DEFAULT_VOLUME_THRESHOLD: Decimal = Decimal("1.5")
DEFAULT_ATR_PERIOD: int = 14
DEFAULT_ATR_MULT: Decimal = Decimal("2.0")
DEFAULT_TARGET_MULT: Decimal = Decimal("3.0")
DEFAULT_RISK_PCT: Decimal = Decimal("0.01")
DEFAULT_EQUITY: Decimal = Decimal("10000")


class VolumeDonchianStrategy(Strategy):
    """Donchian channel break + volume-anomaly gate — long-only, ATR stop."""

    def name(self) -> str:
        return "volume_donchian"

    def version(self) -> str:
        return "0.2.0"

    @property
    def MIN_BARS(self) -> int:  # type: ignore[override]
        # Need ``max(period, vol_window)`` prior bars for the channel-high
        # / volume-average windows, plus ``atr_period + 1`` true-range
        # pairs for the stop sizing, plus 1 "current" bar for the breakout
        # check, plus 1 sentinel (the wrapper drops ``bars[-1]`` before
        # delegating).
        return max(DEFAULT_PERIOD, DEFAULT_VOL_WINDOW) + DEFAULT_ATR_PERIOD + 2

    def _compute_signal_impl(
        self,
        symbol: str,
        history: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        params = config.params
        period = int(params.get("period", DEFAULT_PERIOD))
        vol_window = int(params.get("vol_window", DEFAULT_VOL_WINDOW))
        volume_threshold = _to_decimal(
            params.get("volume_threshold"), default=DEFAULT_VOLUME_THRESHOLD
        )
        atr_period = int(params.get("atr_period", DEFAULT_ATR_PERIOD))
        atr_mult = _to_decimal(params.get("atr_mult"), default=DEFAULT_ATR_MULT)
        target_mult = _to_decimal(params.get("target_mult"), default=DEFAULT_TARGET_MULT)
        risk_pct = _to_decimal(params.get("risk_pct"), default=DEFAULT_RISK_PCT)
        equity = _to_decimal(params.get("equity"), default=DEFAULT_EQUITY)
        sizing_mode = str(params.get("sizing_mode", SIZING_MODE_RISK))
        target_cash = _to_decimal(params.get("target_cash"), default=Decimal("0"))

        bars = history.bars
        # Need enough bars to (a) build the channel-high window of size
        # ``period`` and the volume-average window of size ``vol_window``
        # both excluding the current bar, AND (b) build ``atr_period + 1``
        # ATR pairs.
        required = max(period, vol_window) + 1
        if len(bars) < max(required, atr_period + 1):
            return None

        current_close = bars[-1].close
        current_volume = bars[-1].volume

        # Donchian channel: max high of the prior ``period`` bars,
        # explicitly EXCLUDING the current bar.
        prior_highs = [bar.high for bar in bars[-period - 1 : -1]]
        if len(prior_highs) < period:
            return None
        donchian_high = max(prior_highs)
        if current_close <= donchian_high:
            return None

        # Volume gate: trailing average over prior ``vol_window`` bars,
        # excluding the current bar (otherwise the ratio is tautological).
        prior_volumes = [bar.volume for bar in bars[-vol_window - 1 : -1]]
        if len(prior_volumes) < vol_window:
            return None
        avg_volume = sum(prior_volumes, Decimal("0")) / Decimal(len(prior_volumes))
        if avg_volume <= Decimal("0"):
            return None
        volume_ratio = current_volume / avg_volume
        if volume_ratio < volume_threshold:
            return None

        atr = _compute_atr(bars[-(atr_period + 1) :])
        if atr is None or atr <= Decimal("0"):
            return None

        entry = current_close
        stop = entry - atr_mult * atr
        if stop >= entry:
            return None
        target = entry + target_mult * atr
        # Bracket sanity (WS-C review): a non-positive stop (huge ATR) or a
        # misconfigured target_mult <= 0 (long target at/below entry) would
        # emit an inverted/degenerate bracket the broker rejects or that
        # self-closes the long on the first stop_hit_sweep tick.
        if stop <= Decimal("0") or target <= entry:
            return None
        risk_per_share = entry - stop
        if risk_per_share <= Decimal("0"):
            return None
        quantity = calculate_quantity(
            sizing_mode=sizing_mode,
            entry=entry,
            stop=stop,
            risk_pct=risk_pct,
            equity=equity,
            target_cash=target_cash,
        )
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
            target_price=target,
            confidence_score=None,
            reasoning={
                "strategy": "volume_donchian",
                "period": period,
                "vol_window": vol_window,
                "volume_threshold": str(volume_threshold),
                "donchian_high": str(donchian_high),
                "current_close": str(current_close),
                "current_volume": str(current_volume),
                "avg_volume": str(avg_volume),
                "volume_ratio": str(volume_ratio),
                "atr": str(atr),
                "atr_mult": str(atr_mult),
                "target_mult": str(target_mult),
                "risk_pct": str(risk_pct),
                "equity": str(equity),
                "sizing_mode": sizing_mode,
                "target_cash": str(target_cash),
                "entry": str(entry),
                "stop": str(stop),
                "target": str(target),
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
        result = Decimal(str(value))
    except Exception:
        return default
    # Reject NaN/Inf — see donchian_atr._to_decimal (WS-C review).
    return result if result.is_finite() else default


__all__ = [
    "DEFAULT_ATR_MULT",
    "DEFAULT_ATR_PERIOD",
    "DEFAULT_EQUITY",
    "DEFAULT_PERIOD",
    "DEFAULT_RISK_PCT",
    "DEFAULT_TARGET_MULT",
    "DEFAULT_VOLUME_THRESHOLD",
    "DEFAULT_VOL_WINDOW",
    "VolumeDonchianStrategy",
]
