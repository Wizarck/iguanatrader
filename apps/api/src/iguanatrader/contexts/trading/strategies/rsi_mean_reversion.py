"""RSI mean-reversion strategy — Wilder RSI(14) cross-UP-from-oversold (v1.5).

First counter-trend strategy in the catalogue. Long-only entry when the
Wilder RSI series crosses UP through the ``oversold`` threshold between
``bars[-2]`` and ``bars[-1]`` (i.e. ``rsi_prev < oversold AND
rsi_now >= oversold``). Stop sized off ATR(``atr_period``); quantity
sized from ``risk_pct * equity / (entry - stop)`` like the other
strategies in the registry.

Default params (overridable via :class:`StrategyConfigSnapshot.params`):

* ``rsi_period = 14`` (Wilder canonical).
* ``oversold = 30``.
* ``overbought = 70`` (informational only; v1.5 is long-only).
* ``atr_period = 14``.
* ``atr_mult = 2.0``.
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
from iguanatrader.contexts.trading.strategies.base import Strategy
from iguanatrader.shared.time import now as utc_now

DEFAULT_RSI_PERIOD: int = 14
DEFAULT_OVERSOLD: Decimal = Decimal("30")
DEFAULT_OVERBOUGHT: Decimal = Decimal("70")
DEFAULT_ATR_PERIOD: int = 14
DEFAULT_ATR_MULT: Decimal = Decimal("2.0")
DEFAULT_RISK_PCT: Decimal = Decimal("0.01")
DEFAULT_EQUITY: Decimal = Decimal("10000")


class RSIMeanReversionStrategy(Strategy):
    """Wilder RSI(14) cross-UP-from-oversold long-only counter-trend strategy."""

    def name(self) -> str:
        return "rsi_mean_reversion"

    def version(self) -> str:
        return "0.1.0"

    @property
    def MIN_BARS(self) -> int:  # type: ignore[override]
        # Need ``rsi_period + 1`` closes to seed Wilder smoothing AND a
        # second RSI value (for the prev-vs-now cross check), plus
        # ``atr_period`` true-range pairs for the stop sizing, plus 1
        # extra bar (wrapper drops ``bars[-1]``).
        return DEFAULT_RSI_PERIOD + DEFAULT_ATR_PERIOD + 2

    def _compute_signal_impl(
        self,
        symbol: str,
        history: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        params = config.params
        rsi_period = int(params.get("rsi_period", DEFAULT_RSI_PERIOD))
        oversold = _to_decimal(params.get("oversold"), default=DEFAULT_OVERSOLD)
        atr_period = int(params.get("atr_period", DEFAULT_ATR_PERIOD))
        atr_mult = _to_decimal(params.get("atr_mult"), default=DEFAULT_ATR_MULT)
        risk_pct = _to_decimal(params.get("risk_pct"), default=DEFAULT_RISK_PCT)
        equity = _to_decimal(params.get("equity"), default=DEFAULT_EQUITY)

        bars = history.bars
        # Need rsi_period + 1 closes to compute the first RSI value, plus
        # one more close for the cross-check (prev vs now). And separately
        # ``atr_period + 1`` bars for the ATR true-range pairs.
        if len(bars) < max(rsi_period + 2, atr_period + 1):
            return None

        closes = [bar.close for bar in bars]
        rsi_pair = _compute_rsi_prev_now(closes, rsi_period)
        if rsi_pair is None:
            return None
        rsi_prev, rsi_now = rsi_pair

        # Cross-UP-from-oversold: prev strictly below threshold AND now
        # at/above the threshold. Filters out (a) flat noise above the
        # oversold band and (b) continued plunges still below threshold.
        if not (rsi_prev < oversold and rsi_now >= oversold):
            return None

        atr = _compute_atr(bars[-(atr_period + 1) :])
        if atr is None or atr <= Decimal("0"):
            return None

        entry = closes[-1]
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
                "strategy": "rsi_mean_reversion",
                "rsi_period": rsi_period,
                "oversold": str(oversold),
                "rsi_prev": str(rsi_prev),
                "rsi_now": str(rsi_now),
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


def _compute_rsi_prev_now(closes: list[Decimal], rsi_period: int) -> tuple[Decimal, Decimal] | None:
    """Compute (rsi_prev, rsi_now) using Wilder smoothing.

    Returns ``None`` when ``closes`` is too short. ``avg_loss == 0``
    (strictly rising prices) is treated as RSI = 100 — "perfectly
    bullish", which yields no signal in the mean-reversion regime.
    """
    from itertools import pairwise

    if len(closes) < rsi_period + 2:
        return None

    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for prev, cur in pairwise(closes):
        delta = cur - prev
        if delta > Decimal("0"):
            gains.append(delta)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(-delta)

    # Seed Wilder smoothing with the simple mean of the first
    # ``rsi_period`` gain/loss pairs.
    period_dec = Decimal(rsi_period)
    avg_gain = sum(gains[:rsi_period], Decimal("0")) / period_dec
    avg_loss = sum(losses[:rsi_period], Decimal("0")) / period_dec

    # Roll Wilder smoothing forward across the remaining bars, capturing
    # the second-to-last and last RSI values for the cross-check.
    rsi_prev: Decimal | None = None
    rsi_now: Decimal | None = None
    remaining = len(gains) - rsi_period
    for i in range(remaining):
        idx = rsi_period + i
        avg_gain = (avg_gain * (period_dec - Decimal("1")) + gains[idx]) / period_dec
        avg_loss = (avg_loss * (period_dec - Decimal("1")) + losses[idx]) / period_dec
        rsi_value = _rsi_from_avgs(avg_gain, avg_loss)
        if i == remaining - 2:
            rsi_prev = rsi_value
        if i == remaining - 1:
            rsi_now = rsi_value

    if rsi_prev is None or rsi_now is None:
        return None
    return rsi_prev, rsi_now


def _rsi_from_avgs(avg_gain: Decimal, avg_loss: Decimal) -> Decimal:
    if avg_loss == Decimal("0"):
        # Strictly rising — RS = +inf → RSI = 100.
        return Decimal("100")
    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


# TODO(strategies-indicators-shared): hoist when 3rd caller lands.
def _compute_atr(bars: Any) -> Decimal | None:
    """Wilder ATR over ``bars`` — needs at least 2 bars.

    Copy of :func:`donchian_atr._compute_atr` per
    ``openspec/changes/strategy-rsi-mean-reversion/proposal.md`` §"
    ``_compute_atr`` reuse" (decision A: copy-paste; hoist when the 3rd
    caller lands).
    """
    from itertools import pairwise

    if len(bars) < 2:
        return None
    true_ranges: list[Decimal] = []
    for prev, cur in pairwise(bars):
        tr1 = cur.high - cur.low
        tr2 = abs(cur.high - prev.close)
        tr3 = abs(cur.low - prev.close)
        true_ranges.append(max(tr1, tr2, tr3))
    if not true_ranges:
        return None
    total = sum(true_ranges, Decimal("0"))
    return total / Decimal(len(true_ranges))


__all__ = [
    "DEFAULT_ATR_MULT",
    "DEFAULT_ATR_PERIOD",
    "DEFAULT_EQUITY",
    "DEFAULT_OVERBOUGHT",
    "DEFAULT_OVERSOLD",
    "DEFAULT_RISK_PCT",
    "DEFAULT_RSI_PERIOD",
    "RSIMeanReversionStrategy",
]
