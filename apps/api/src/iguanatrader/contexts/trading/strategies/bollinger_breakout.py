"""Bollinger band breakout strategy — SMA(20) ± 2-stdev upper-band breakout (v1.5).

Second trend-following strategy in the catalogue and volatility-adaptive
complement to :class:`DonchianATRStrategy` (which uses the raw N-bar high).
Long-only entry when the latest close strictly exceeds the upper Bollinger
band ``SMA(period) + num_std * stdev(period)``. Optional squeeze filter
gates the signal on recent bandwidth compression. Stop sized off
``ATR(atr_period)``; quantity sized from
``risk_pct * equity / (entry - stop)`` like the other strategies in the
registry.

Default params (overridable via :class:`StrategyConfigSnapshot.params`):

* ``period = 20`` (canonical Bollinger default).
* ``num_std = 2.0`` (the standard 2-stdev band — captures ~95 % of moves in a
  normal regime; values outside the band qualify as breakout candidates).
* ``squeeze_threshold = None`` (squeeze filter disabled by default; set to
  e.g. ``0.05`` to require bandwidth < 5 % of SMA over the prior
  ``squeeze_lookback`` bars before signalling).
* ``squeeze_lookback = 6`` (how many recent bars must show compressed
  bandwidth when the squeeze filter is active).
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

DEFAULT_PERIOD: int = 20
DEFAULT_NUM_STD: Decimal = Decimal("2.0")
DEFAULT_SQUEEZE_THRESHOLD: Decimal | None = None
DEFAULT_SQUEEZE_LOOKBACK: int = 6
DEFAULT_ATR_PERIOD: int = 14
DEFAULT_ATR_MULT: Decimal = Decimal("2.0")
DEFAULT_RISK_PCT: Decimal = Decimal("0.01")
DEFAULT_EQUITY: Decimal = Decimal("10000")


class BollingerBreakoutStrategy(Strategy):
    """SMA(20) ± 2-stdev Bollinger upper-band breakout — long-only, ATR stop."""

    def name(self) -> str:
        return "bollinger_breakout"

    def version(self) -> str:
        return "0.1.0"

    @property
    def MIN_BARS(self) -> int:  # type: ignore[override]
        # Need ``period`` closes for the SMA + stdev, ``atr_period`` true-
        # range pairs for the stop, plus 2 sentinel bars (wrapper drops
        # bars[-1]; we also want headroom for squeeze-lookback inspection).
        return DEFAULT_PERIOD + DEFAULT_ATR_PERIOD + 2

    def _compute_signal_impl(
        self,
        symbol: str,
        history: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        params = config.params
        period = int(params.get("period", DEFAULT_PERIOD))
        num_std = _to_decimal(params.get("num_std"), default=DEFAULT_NUM_STD)
        squeeze_threshold = _to_optional_decimal(params.get("squeeze_threshold"))
        squeeze_lookback = int(params.get("squeeze_lookback", DEFAULT_SQUEEZE_LOOKBACK))
        atr_period = int(params.get("atr_period", DEFAULT_ATR_PERIOD))
        atr_mult = _to_decimal(params.get("atr_mult"), default=DEFAULT_ATR_MULT)
        risk_pct = _to_decimal(params.get("risk_pct"), default=DEFAULT_RISK_PCT)
        equity = _to_decimal(params.get("equity"), default=DEFAULT_EQUITY)

        bars = history.bars
        # Need ``period`` closes for the current band, ``atr_period + 1``
        # bars for the ATR pairs, and (when the squeeze filter is active)
        # an extra ``squeeze_lookback`` bars of priors to evaluate the
        # historical bandwidth.
        min_required = max(period, atr_period + 1)
        if squeeze_threshold is not None:
            min_required = max(min_required, period + squeeze_lookback)
        if len(bars) < min_required:
            return None

        closes = [bar.close for bar in bars]
        band = _compute_bollinger_bands(closes[-period:], num_std)
        if band is None:
            return None
        sma, stdev, upper_band, lower_band = band

        # Strictly above the upper band: the proposal explicitly excludes
        # the "touch" case (close == upper) so that flat/equal-bar
        # histories never trip the signal.
        if closes[-1] <= upper_band:
            return None

        if squeeze_threshold is not None and not _squeeze_compressed(
            closes=closes,
            period=period,
            num_std=num_std,
            lookback=squeeze_lookback,
            threshold=squeeze_threshold,
        ):
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

        bandwidth_ratio: Decimal = (
            (upper_band - lower_band) / sma if sma > Decimal("0") else Decimal("0")
        )

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
                "strategy": "bollinger_breakout",
                "period": period,
                "num_std": str(num_std),
                "sma": str(sma),
                "stdev": str(stdev),
                "upper_band": str(upper_band),
                "lower_band": str(lower_band),
                "bandwidth_ratio": str(bandwidth_ratio),
                "squeeze_filter_active": squeeze_threshold is not None,
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


def _to_optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _compute_bollinger_bands(
    closes: list[Decimal], num_std: Decimal
) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    """Compute (sma, stdev, upper_band, lower_band) over ``closes``.

    Population standard deviation (the canonical Bollinger choice — John
    Bollinger's original 1980s formulation divides by ``N`` not ``N-1``).
    Returns ``None`` when ``closes`` is empty.
    """
    n = len(closes)
    if n == 0:
        return None
    n_dec = Decimal(n)
    sma = sum(closes, Decimal("0")) / n_dec
    variance_sum = sum(((c - sma) * (c - sma) for c in closes), Decimal("0"))
    variance = variance_sum / n_dec
    # Decimal has no .sqrt(); convert via the closest-rational pathway.
    stdev = variance.sqrt() if hasattr(variance, "sqrt") else Decimal(str(float(variance) ** 0.5))
    upper_band = sma + num_std * stdev
    lower_band = sma - num_std * stdev
    return sma, stdev, upper_band, lower_band


def _squeeze_compressed(
    *,
    closes: list[Decimal],
    period: int,
    num_std: Decimal,
    lookback: int,
    threshold: Decimal,
) -> bool:
    """Return True iff every band over the prior ``lookback`` bars was tight.

    "Tight" = ``(upper - lower) / sma < threshold``. We inspect the band
    computed at each of the prior ``lookback`` bars (i.e. excluding the
    current breakout bar) using a sliding window of length ``period``.
    """
    if lookback <= 0:
        return True
    # The window for "the bar just before the current one" is
    # ``closes[-(period+1):-1]``; for ``k`` bars back it is
    # ``closes[-(period+k):-k]``. We need ``lookback`` such windows.
    if len(closes) < period + lookback:
        return False
    for k in range(1, lookback + 1):
        end = -k
        start = -(period + k)
        window = closes[start:end]
        band = _compute_bollinger_bands(window, num_std)
        if band is None:
            return False
        sma, _stdev, upper, lower = band
        if sma <= Decimal("0"):
            return False
        bandwidth_ratio = (upper - lower) / sma
        if bandwidth_ratio >= threshold:
            return False
    return True


# Forward-pointer comment (strategies-indicators-shared): ATR helper
# duplicated from ``donchian_atr``; hoist scheduled for the slice that
# brings the 4th caller (per cross-slice agreement after PR #155 retro —
# 3rd caller now present, decision is to defer hoist until MACD lands).
def _compute_atr(bars: Any) -> Decimal | None:
    """Wilder ATR over ``bars`` — needs at least 2 bars.

    Copy of :func:`donchian_atr._compute_atr` /
    :func:`rsi_mean_reversion._compute_atr` per
    ``openspec/changes/strategy-bollinger-breakout/proposal.md`` §"
    ``_compute_atr`` reuse" (decision: still copy at the 3rd caller; hoist
    when the 4th caller emerges).
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
    "DEFAULT_NUM_STD",
    "DEFAULT_PERIOD",
    "DEFAULT_RISK_PCT",
    "DEFAULT_SQUEEZE_LOOKBACK",
    "DEFAULT_SQUEEZE_THRESHOLD",
    "BollingerBreakoutStrategy",
]
