"""Donchian-channel breakout with ATR-based stop + target sizing (slice T3).

Bidirectional (long + short) v0.2:

* **Long** entry when ``close >= max(prior-lookback highs)``;
  stop ``= entry - atr_mult * ATR``; target ``= entry + target_mult * ATR``.
* **Short** entry when ``close <= min(prior-lookback lows)``;
  stop ``= entry + atr_mult * ATR``; target ``= entry - target_mult * ATR``.

Position size: ``floor(risk_pct * equity / abs(entry - stop))`` (whole
shares — IBKR rejects fractional bracket/STP quantities) — identical risk
envelope on both sides. The exit levels are consumed by the
side-aware ``stop_hit_sweep`` (long: close<=stop / close>=target; short:
close>=stop / close<=target).

Default params (overridable via :class:`StrategyConfigSnapshot.params`):

* ``lookback = 20`` (Turtle Traders system 1 minimum).
* ``atr_period = 14``.
* ``atr_mult = 2.0`` (protective stop distance, in ATRs).
* ``target_mult = 3.0`` (take-profit distance, in ATRs).
* ``risk_pct = 0.01`` (1% of equity per trade, NFR-R6).
* ``equity = 10000.0`` (default fallback when broker equity not yet
  available; production caller passes the real equity).
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import UUID, uuid4

from iguanatrader.contexts.trading.ports import (
    BarHistory,
    Proposal,
    StrategyConfigSnapshot,
)
from iguanatrader.contexts.trading.strategies._indicators import _compute_atr
from iguanatrader.contexts.trading.strategies.base import Strategy
from iguanatrader.shared.time import now as utc_now

DEFAULT_LOOKBACK: int = 20
DEFAULT_ATR_PERIOD: int = 14
DEFAULT_ATR_MULT: Decimal = Decimal("2.0")
DEFAULT_TARGET_MULT: Decimal = Decimal("3.0")
DEFAULT_RISK_PCT: Decimal = Decimal("0.01")
DEFAULT_EQUITY: Decimal = Decimal("10000")


class DonchianATRStrategy(Strategy):
    """Donchian breakout v0.2 — long+short, ATR stop+target, risk-pct sizing."""

    def name(self) -> str:
        return "donchian_atr"

    def version(self) -> str:
        return "0.2.0"

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
        target_mult = _to_decimal(params.get("target_mult"), default=DEFAULT_TARGET_MULT)
        risk_pct = _to_decimal(params.get("risk_pct"), default=DEFAULT_RISK_PCT)
        equity = _to_decimal(params.get("equity"), default=DEFAULT_EQUITY)

        bars = history.bars
        if len(bars) < lookback + atr_period:
            return None

        latest_close = bars[-1].close
        # Donchian channel: max high / min low of the prior `lookback` bars,
        # EXCLUDING the current bar (we test whether the current close
        # breaks the prior channel; including bars[-1] would make the upper
        # comparison trivially fail because bars[-1].high >= bars[-1].close).
        window = bars[-lookback - 1 : -1]
        channel_high = max(bar.high for bar in window)
        channel_low = min(bar.low for bar in window)

        # Direction: upper-channel break → long; lower-channel break → short.
        # Long takes precedence (a single close cannot break both unless the
        # channel is degenerate). No break → no signal.
        if latest_close >= channel_high:
            side = "buy"
        elif latest_close <= channel_low:
            side = "sell"
        else:
            return None

        # ATR(atr_period) over the trailing window — Wilder's smoothing.
        atr = _compute_atr(bars[-(atr_period + 1) :])
        if atr is None or atr <= Decimal("0"):
            return None

        entry = latest_close
        stop_distance = atr_mult * atr
        target_distance = target_mult * atr
        if side == "buy":
            stop = entry - stop_distance
            target = entry + target_distance
            breakout_level = channel_high
        else:  # short
            stop = entry + stop_distance
            target = entry - target_distance
            breakout_level = channel_low

        # Sanity: stop on the protective side of entry; target positive.
        risk_per_share = abs(entry - stop)
        if risk_per_share <= Decimal("0") or target <= Decimal("0"):
            return None
        risk_dollars = risk_pct * equity
        # Whole-share sizing: IBKR rejects bracket/STP orders with fractional
        # quantities (and the paper account isn't fractional-enabled), so floor
        # to an integer share count. Flooring is the risk-conservative direction
        # (actual risk <= risk_dollars). When 1% of equity can't afford even a
        # single share at this stop distance the signal is skipped by the <=0
        # guard below rather than forced up to 1 share (which would breach the
        # risk_pct envelope).
        quantity = (risk_dollars / risk_per_share).to_integral_value(rounding=ROUND_DOWN)
        if quantity <= Decimal("0"):
            return None

        correlation_id: UUID = uuid4()
        return Proposal(
            tenant_id=config.tenant_id,
            strategy_config_id=config.id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price_indicative=entry,
            stop_price=stop,
            target_price=target,
            confidence_score=None,
            reasoning={
                "strategy": "donchian_atr",
                "direction": "long" if side == "buy" else "short",
                "lookback": lookback,
                "channel_high": str(channel_high),
                "channel_low": str(channel_low),
                "breakout_level": str(breakout_level),
                "atr": str(atr),
                "atr_mult": str(atr_mult),
                "target_mult": str(target_mult),
                "risk_pct": str(risk_pct),
                "equity": str(equity),
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
        return Decimal(str(value))
    except Exception:
        return default


__all__ = [
    "DEFAULT_ATR_MULT",
    "DEFAULT_ATR_PERIOD",
    "DEFAULT_LOOKBACK",
    "DEFAULT_RISK_PCT",
    "DEFAULT_TARGET_MULT",
    "DonchianATRStrategy",
]
