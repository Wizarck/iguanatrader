"""Trader KPI stat block — pure-function computation from ingested facts.

Slice ``research-stat-block`` (2026-05-18). Surfaces the snapshot
KPIs Arturo asked for: current price + day chg, 52-week range,
volume, realized volatility, beta vs SPY, valuation multiples,
RSI(14), SMA position, relative strength, analyst consensus.

The module is intentionally framework-light:

* Inputs are raw research_fact rows (``historical_prices_window``
  payload + latest ``fundamentals`` / ``analyst_ratings`` value_jsonb).
* All numerical work is pure Python — no numpy / pandas dep. The
  series are small (≤300 daily bars per symbol) so manual loops
  outperform allocating numpy arrays.
* Output is a frozen :class:`BriefStats` dataclass with every field
  Optional so the frontend can render placeholders when an upstream
  source is missing.

Used by the new ``GET /api/v1/research/stats/{symbol}`` route.
"""

from __future__ import annotations

import itertools
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

#: Benchmark symbol for relative-strength + beta computations.
BENCHMARK_SYMBOL = "SPY"

#: Trading days per year, used for vol annualisation.
TRADING_DAYS_PER_YEAR = 252

#: Window for the 20-day realized volatility.
VOL_WINDOW = 20

#: RSI lookback (Wilder convention).
RSI_WINDOW = 14

#: Beta lookback in trading days (~3 months).
BETA_WINDOW = 60


@dataclass(frozen=True, slots=True)
class BriefStats:
    """Snapshot KPIs returned by ``GET /research/stats/{symbol}``."""

    symbol: str
    as_of: str | None  # ISO date of the latest price bar

    # Price block.
    last_price: float | None
    day_change_pct: float | None
    high_52w: float | None
    low_52w: float | None
    position_in_52w_pct: float | None
    avg_volume_20d: float | None

    # Risk block.
    volatility_20d_annualized: float | None
    beta_vs_spy_60d: float | None

    # Valuation block.
    forward_pe: float | None
    pe_ratio: float | None
    price_to_book: float | None
    market_cap: float | None

    # Momentum block.
    rsi_14: float | None
    sma_50: float | None
    sma_200: float | None
    pos_vs_sma_50_pct: float | None
    pos_vs_sma_200_pct: float | None
    return_3m_pct: float | None
    return_12m_pct: float | None
    relative_strength_vs_spy_3m_pct: float | None
    relative_strength_vs_spy_12m_pct: float | None

    # Analyst block.
    analyst_target_price: float | None
    analyst_count: int | None
    upside_to_target_pct: float | None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_stats(
    *,
    symbol: str,
    prices_payload: dict[str, Any] | None,
    benchmark_payload: dict[str, Any] | None,
    fundamentals_payload: dict[str, Any] | None,
    analyst_payload: dict[str, Any] | None,
) -> BriefStats:
    """Compute the full :class:`BriefStats` from the latest ingested facts.

    Each ``*_payload`` arg is the ``value_jsonb`` of the latest fact of
    the corresponding kind. Missing payloads yield ``None`` fields —
    the function never raises on missing data.
    """
    bars = _bars_from_payload(prices_payload)
    bench_bars = _bars_from_payload(benchmark_payload)

    closes = [b["close"] for b in bars if "close" in b and b["close"] is not None]
    volumes = [b.get("volume") for b in bars]

    last_price = closes[-1] if closes else None
    prev_close = closes[-2] if len(closes) >= 2 else None
    day_chg = _safe_pct_change(prev_close, last_price)

    high_52w = max(closes) if closes else None
    low_52w = min(closes) if closes else None
    pos_52w = (
        (last_price - low_52w) / (high_52w - low_52w) * 100.0
        if (
            last_price is not None
            and high_52w is not None
            and low_52w is not None
            and high_52w > low_52w
        )
        else None
    )

    avg_vol_20d = _trailing_average([v for v in volumes if isinstance(v, (int, float))], VOL_WINDOW)

    vol_annualised = _vol_annualised(closes, VOL_WINDOW)
    bench_closes = [b["close"] for b in bench_bars if "close" in b and b["close"] is not None]
    beta = _beta(closes, bench_closes, BETA_WINDOW)

    rsi = _rsi(closes, RSI_WINDOW)
    sma_50 = _trailing_average(closes, 50)
    sma_200 = _trailing_average(closes, 200)
    pos_vs_50 = _safe_pct_change(sma_50, last_price)
    pos_vs_200 = _safe_pct_change(sma_200, last_price)

    ret_3m = _trailing_return(closes, 63)  # ~3 months of trading days
    ret_12m = _trailing_return(closes, 252)
    bench_ret_3m = _trailing_return(bench_closes, 63)
    bench_ret_12m = _trailing_return(bench_closes, 252)
    rel_3m = _diff_pct(ret_3m, bench_ret_3m)
    rel_12m = _diff_pct(ret_12m, bench_ret_12m)

    forward_pe = _coerce_float(_extract(fundamentals_payload, "forward_pe"))
    pe_ratio = _coerce_float(_extract(fundamentals_payload, "pe_ratio"))
    pb_ratio = _coerce_float(_extract(fundamentals_payload, "price_to_book", "pb_ratio"))
    market_cap = _coerce_float(_extract(fundamentals_payload, "market_cap"))

    analyst_target = _coerce_float(
        _extract(analyst_payload, "analyst_target_price", "target_price"),
    )
    analyst_count_raw = _extract(analyst_payload, "analyst_count", "number_of_analysts")
    analyst_count = int(analyst_count_raw) if isinstance(analyst_count_raw, (int, float)) else None
    upside: float | None = None
    if analyst_target is not None and last_price is not None and last_price != 0:
        upside = (analyst_target - last_price) / last_price * 100.0

    return BriefStats(
        symbol=symbol,
        as_of=_iso_date(bars[-1].get("date")) if bars else None,
        last_price=last_price,
        day_change_pct=day_chg,
        high_52w=high_52w,
        low_52w=low_52w,
        position_in_52w_pct=pos_52w,
        avg_volume_20d=avg_vol_20d,
        volatility_20d_annualized=vol_annualised,
        beta_vs_spy_60d=beta,
        forward_pe=forward_pe,
        pe_ratio=pe_ratio,
        price_to_book=pb_ratio,
        market_cap=market_cap,
        rsi_14=rsi,
        sma_50=sma_50,
        sma_200=sma_200,
        pos_vs_sma_50_pct=pos_vs_50,
        pos_vs_sma_200_pct=pos_vs_200,
        return_3m_pct=ret_3m,
        return_12m_pct=ret_12m,
        relative_strength_vs_spy_3m_pct=rel_3m,
        relative_strength_vs_spy_12m_pct=rel_12m,
        analyst_target_price=analyst_target,
        analyst_count=analyst_count,
        upside_to_target_pct=upside,
    )


# ---------------------------------------------------------------------------
# Helpers — pure functions, easy to unit-test in isolation.
# ---------------------------------------------------------------------------


def _bars_from_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    raw = payload.get("bars")
    if not isinstance(raw, list):
        return []
    return [b for b in raw if isinstance(b, dict)]


def _safe_pct_change(base: float | None, current: float | None) -> float | None:
    if base is None or current is None or base == 0:
        return None
    return (current - base) / base * 100.0


def _diff_pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b


def _trailing_average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    tail = values[-window:]
    return sum(tail) / window


def _trailing_return(closes: list[float], window: int) -> float | None:
    if len(closes) <= window:
        return None
    return _safe_pct_change(closes[-window - 1], closes[-1])


def _vol_annualised(closes: list[float], window: int) -> float | None:
    if len(closes) <= window:
        return None
    daily_returns: list[float] = []
    for prev, cur in zip(closes[-window - 1 : -1], closes[-window:], strict=True):
        if prev == 0:
            return None
        daily_returns.append((cur - prev) / prev)
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean) ** 2 for r in daily_returns) / max(len(daily_returns) - 1, 1)
    stdev = math.sqrt(variance)
    return stdev * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0  # percent


def _rsi(closes: list[float], window: int) -> float | None:
    """Wilder's RSI(14). Returns 0-100 or ``None`` if too few bars."""
    if len(closes) <= window:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, cur in itertools.pairwise(closes):
        delta = cur - prev
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    for g, loss in zip(gains[window:], losses[window:], strict=True):
        avg_gain = (avg_gain * (window - 1) + g) / window
        avg_loss = (avg_loss * (window - 1) + loss) / window
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _beta(closes: list[float], bench_closes: list[float], window: int) -> float | None:
    """Covariance of trailing-``window`` daily returns vs benchmark."""
    if len(closes) <= window or len(bench_closes) <= window:
        return None
    tail = closes[-(window + 1) :]
    bench_tail = bench_closes[-(window + 1) :]
    asset_returns = _daily_returns(tail)
    bench_returns = _daily_returns(bench_tail)
    n = min(len(asset_returns), len(bench_returns))
    if n < 2:
        return None
    asset_returns = asset_returns[-n:]
    bench_returns = bench_returns[-n:]
    mean_a = sum(asset_returns) / n
    mean_b = sum(bench_returns) / n
    cov = sum(
        (a - mean_a) * (b - mean_b) for a, b in zip(asset_returns, bench_returns, strict=True)
    ) / max(n - 1, 1)
    var_b = sum((b - mean_b) ** 2 for b in bench_returns) / max(n - 1, 1)
    if var_b == 0:
        return None
    return cov / var_b


def _daily_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for prev, cur in itertools.pairwise(closes):
        if prev == 0:
            continue
        out.append((cur - prev) / prev)
    return out


def _extract(payload: dict[str, Any] | None, *keys: str) -> Any:
    if not payload:
        return None
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


__all__ = [
    "BENCHMARK_SYMBOL",
    "BETA_WINDOW",
    "RSI_WINDOW",
    "TRADING_DAYS_PER_YEAR",
    "VOL_WINDOW",
    "BriefStats",
    "compute_stats",
]
