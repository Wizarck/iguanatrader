"""SMA-cross sanity-check strategy (slice T3 manager validation).

Long-only entry: ``SMA(fast)`` crossed above ``SMA(slow)`` between
``bars[-2]`` and ``bars[-1]``. Position size: ``risk_pct * equity /
volatility`` where ``volatility`` is the rolling stdev of returns.

Defaults: ``fast=50``, ``slow=200``, ``vol_window=20``, ``risk_pct=0.01``.
"""

from __future__ import annotations

from decimal import Decimal
from statistics import stdev
from typing import Any
from uuid import UUID, uuid4

from iguanatrader.contexts.trading.ports import (
    BarHistory,
    Proposal,
    StrategyConfigSnapshot,
)
from iguanatrader.contexts.trading.strategies.base import Strategy
from iguanatrader.contexts.trading.strategies.sizing import (
    SIZING_MODE_RISK,
    calculate_quantity,
)
from iguanatrader.shared.time import now as utc_now

DEFAULT_FAST: int = 50
DEFAULT_SLOW: int = 200
DEFAULT_VOL_WINDOW: int = 20
DEFAULT_RISK_PCT: Decimal = Decimal("0.01")
DEFAULT_EQUITY: Decimal = Decimal("10000")


class SMACrossStrategy(Strategy):
    """SMA-cross long-only strategy (sanity-check for the manager)."""

    def name(self) -> str:
        return "sma_cross"

    def version(self) -> str:
        return "0.1.0"

    @property
    def MIN_BARS(self) -> int:  # type: ignore[override]
        return DEFAULT_SLOW + 1

    def _compute_signal_impl(
        self,
        symbol: str,
        history: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        params = config.params
        fast = int(params.get("fast", DEFAULT_FAST))
        slow = int(params.get("slow", DEFAULT_SLOW))
        vol_window = int(params.get("vol_window", DEFAULT_VOL_WINDOW))
        risk_pct = _to_decimal(params.get("risk_pct"), default=DEFAULT_RISK_PCT)
        equity = _to_decimal(params.get("equity"), default=DEFAULT_EQUITY)
        sizing_mode = str(params.get("sizing_mode", SIZING_MODE_RISK))
        target_cash = _to_decimal(params.get("target_cash"), default=Decimal("0"))

        bars = history.bars
        if len(bars) < slow + 1:
            return None

        closes = [bar.close for bar in bars]
        sma_fast_now = _sma(closes[-fast:])
        sma_slow_now = _sma(closes[-slow:])
        sma_fast_prev = _sma(closes[-fast - 1 : -1])
        sma_slow_prev = _sma(closes[-slow - 1 : -1])
        if any(v is None for v in (sma_fast_now, sma_slow_now, sma_fast_prev, sma_slow_prev)):
            return None
        # Type narrowing for mypy.
        assert sma_fast_now is not None
        assert sma_slow_now is not None
        assert sma_fast_prev is not None
        assert sma_slow_prev is not None

        # Cross-up condition: prev fast <= prev slow AND now fast > now slow.
        if not (sma_fast_prev <= sma_slow_prev and sma_fast_now > sma_slow_now):
            return None

        # Volatility-based sizing.
        rets = [
            (cur - prev) / prev if prev > 0 else Decimal("0")
            for prev, cur in zip(closes[-vol_window - 1 : -1], closes[-vol_window:], strict=False)
        ]
        if len(rets) < 2:
            return None
        vol = Decimal(str(stdev([float(r) for r in rets])))
        if vol <= Decimal("0"):
            return None

        entry = closes[-1]
        # Stop = entry - 2 * volatility * entry.
        stop = entry - (Decimal("2") * vol * entry)
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
            confidence_score=None,
            reasoning={
                "strategy": "sma_cross",
                "fast": fast,
                "slow": slow,
                "sma_fast_now": str(sma_fast_now),
                "sma_slow_now": str(sma_slow_now),
                "vol": str(vol),
                "sizing_mode": sizing_mode,
                "target_cash": str(target_cash),
                "entry": str(entry),
                "stop": str(stop),
                "computed_at": utc_now().isoformat(),
            },
            mode=str(params.get("mode", "paper")),
            correlation_id=correlation_id,
            metadata={"version": self.version()},
        )


def _sma(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _to_decimal(value: Any, *, default: Decimal) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


__all__ = [
    "DEFAULT_FAST",
    "DEFAULT_RISK_PCT",
    "DEFAULT_SLOW",
    "DEFAULT_VOL_WINDOW",
    "SMACrossStrategy",
]
