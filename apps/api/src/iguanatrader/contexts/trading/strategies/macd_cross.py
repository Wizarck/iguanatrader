"""MACD signal-line cross-up strategy — Appel canonical 12/26/9 (v1.5).

Third v1.5 momentum strategy in the catalogue. Long-only entry when the
MACD line (fast EMA - slow EMA) crosses **up** through its signal line
(EMA of MACD) between ``bars[-2]`` and ``bars[-1]`` — i.e.
``macd_prev <= signal_prev AND macd_now > signal_now``. Optional
``bias_filter`` adds a zero-line gate (``"positive"`` requires
``macd_now > 0`` at cross; ``"negative"`` requires ``macd_now < 0``;
``None`` disables). Stop sized off ``ATR(atr_period)``; quantity sized
from ``risk_pct * equity / (entry - stop)`` matching the rest of the
registry.

Default params (overridable via :class:`StrategyConfigSnapshot.params`):

* ``fast = 12`` (Appel canonical).
* ``slow = 26``.
* ``signal = 9``.
* ``bias_filter = None`` (no zero-line filter; set to ``"positive"`` to
  require ``macd > 0`` at cross or ``"negative"`` to require
  ``macd < 0``).
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

DEFAULT_FAST: int = 12
DEFAULT_SLOW: int = 26
DEFAULT_SIGNAL: int = 9
DEFAULT_BIAS_FILTER: str | None = None
DEFAULT_ATR_PERIOD: int = 14
DEFAULT_ATR_MULT: Decimal = Decimal("2.0")
DEFAULT_TARGET_MULT: Decimal = Decimal("3.0")
DEFAULT_RISK_PCT: Decimal = Decimal("0.01")
DEFAULT_EQUITY: Decimal = Decimal("10000")


class MACDCrossStrategy(Strategy):
    """Appel 12/26/9 MACD signal-line cross-up — long-only, ATR stop."""

    def name(self) -> str:
        return "macd_cross"

    def version(self) -> str:
        return "0.2.0"

    @property
    def MIN_BARS(self) -> int:  # type: ignore[override]
        # Need ``slow`` closes to seed the slow EMA, then another
        # ``signal`` MACD points to seed the signal EMA, plus 1 more bar
        # to expose ``(macd_prev, macd_now)`` and ``(signal_prev,
        # signal_now)`` for the cross-check. Add ``atr_period + 1`` true-
        # range pairs for the stop sizing and 1 sentinel bar (the wrapper
        # drops ``bars[-1]`` before delegating).
        return DEFAULT_SLOW + DEFAULT_SIGNAL + DEFAULT_ATR_PERIOD + 2

    def _compute_signal_impl(
        self,
        symbol: str,
        history: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        params = config.params
        fast = int(params.get("fast", DEFAULT_FAST))
        slow = int(params.get("slow", DEFAULT_SLOW))
        signal_period = int(params.get("signal", DEFAULT_SIGNAL))
        bias_filter = _to_optional_str(params.get("bias_filter", DEFAULT_BIAS_FILTER))
        atr_period = int(params.get("atr_period", DEFAULT_ATR_PERIOD))
        atr_mult = _to_decimal(params.get("atr_mult"), default=DEFAULT_ATR_MULT)
        target_mult = _to_decimal(params.get("target_mult"), default=DEFAULT_TARGET_MULT)
        risk_pct = _to_decimal(params.get("risk_pct"), default=DEFAULT_RISK_PCT)
        equity = _to_decimal(params.get("equity"), default=DEFAULT_EQUITY)
        sizing_mode = str(params.get("sizing_mode", SIZING_MODE_RISK))
        target_cash = _to_decimal(params.get("target_cash"), default=Decimal("0"))

        bars = history.bars
        # Need enough closes to (a) seed both EMAs and the signal EMA
        # AND have 2 trailing values for the cross-check, AND (b) build
        # ``atr_period + 1`` ATR pairs.
        min_closes = slow + signal_period + 1
        if len(bars) < max(min_closes, atr_period + 1):
            return None

        closes = [bar.close for bar in bars]
        cross_state = _compute_macd_cross_state(
            closes=closes,
            fast=fast,
            slow=slow,
            signal_period=signal_period,
        )
        if cross_state is None:
            return None
        macd_prev, macd_now, signal_prev, signal_now = cross_state

        # Cross-up: prev MACD at/below the signal AND now strictly above.
        if not (macd_prev <= signal_prev and macd_now > signal_now):
            return None

        # Optional zero-line bias filter on the post-cross MACD.
        if bias_filter == "positive" and macd_now <= Decimal("0"):
            return None
        if bias_filter == "negative" and macd_now >= Decimal("0"):
            return None

        atr = _compute_atr(bars[-(atr_period + 1) :])
        if atr is None or atr <= Decimal("0"):
            return None

        entry = closes[-1]
        stop = entry - atr_mult * atr
        if stop >= entry:
            return None
        # Hypothesis-discovered edge: small entry + large ATR drives stop
        # below zero. Reject — a negative stop violates the proposal
        # invariant `stop_price > 0` and would crash downstream sizing.
        if stop <= Decimal("0"):
            return None
        target = entry + target_mult * atr
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
                "strategy": "macd_cross",
                "fast": fast,
                "slow": slow,
                "signal": signal_period,
                "bias_filter": bias_filter,
                "macd_prev": str(macd_prev),
                "macd_now": str(macd_now),
                "signal_prev": str(signal_prev),
                "signal_now": str(signal_now),
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
        return Decimal(str(value))
    except Exception:
        return default


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _ema_series(values: list[Decimal], period: int) -> list[Decimal]:
    """Compute the Appel canonical EMA series over ``values``.

    Seed: simple mean of the first ``period`` entries (the seed lands at
    index ``period - 1``). Subsequent values follow
    ``EMA[t] = value[t] * k + EMA[t-1] * (1 - k)`` with
    ``k = 2 / (period + 1)``. Returns the EMA values from index
    ``period - 1`` onwards (length ``len(values) - period + 1``).
    """
    if period <= 0 or len(values) < period:
        return []
    period_dec = Decimal(period)
    k = Decimal("2") / (period_dec + Decimal("1"))
    one_minus_k = Decimal("1") - k

    seed = sum(values[:period], Decimal("0")) / period_dec
    out: list[Decimal] = [seed]
    prev = seed
    for v in values[period:]:
        cur = v * k + prev * one_minus_k
        out.append(cur)
        prev = cur
    return out


def _compute_macd_cross_state(
    *,
    closes: list[Decimal],
    fast: int,
    slow: int,
    signal_period: int,
) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    """Compute ``(macd_prev, macd_now, signal_prev, signal_now)``.

    Single-pass: builds the fast + slow EMAs over the full closes series,
    derives the MACD series on the aligned overlap (i.e. starting at
    ``slow - 1``), then builds the signal-line EMA over the MACD series.
    Returns ``None`` when the input series is too short to yield at least
    two signal-line values (needed for the prev/now cross check).
    """
    if slow <= fast:
        return None

    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)
    if not ema_fast or not ema_slow:
        return None

    # Align the two EMA series so they share an index basis. ``ema_fast``
    # starts at ``fast - 1``; ``ema_slow`` starts at ``slow - 1``. Drop
    # the leading ``slow - fast`` ema_fast entries.
    offset = slow - fast
    if len(ema_fast) <= offset:
        return None
    ema_fast_aligned = ema_fast[offset:]

    if len(ema_fast_aligned) != len(ema_slow):
        # Defensive: alignment should be exact, but bail rather than emit
        # a corrupt signal.
        return None

    macd_series = [f - s for f, s in zip(ema_fast_aligned, ema_slow, strict=True)]
    signal_series = _ema_series(macd_series, signal_period)
    if len(signal_series) < 2:
        return None
    # macd_series is co-indexed with signal_series starting at
    # ``signal_period - 1`` of macd_series. So the macd values that pair
    # with signal_series[-2] and signal_series[-1] are macd_series[-2]
    # and macd_series[-1] respectively (latest two MACD points map to
    # the latest two signal points by construction).
    macd_prev = macd_series[-2]
    macd_now = macd_series[-1]
    signal_prev = signal_series[-2]
    signal_now = signal_series[-1]
    return macd_prev, macd_now, signal_prev, signal_now


__all__ = [
    "DEFAULT_ATR_MULT",
    "DEFAULT_ATR_PERIOD",
    "DEFAULT_BIAS_FILTER",
    "DEFAULT_EQUITY",
    "DEFAULT_FAST",
    "DEFAULT_RISK_PCT",
    "DEFAULT_SIGNAL",
    "DEFAULT_SLOW",
    "DEFAULT_TARGET_MULT",
    "MACDCrossStrategy",
]
