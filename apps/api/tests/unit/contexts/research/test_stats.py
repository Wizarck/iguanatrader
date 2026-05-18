"""Unit tests for ``compute_stats`` (slice research-stat-block).

Pure-function tests — no DB, no FastAPI. Drives the computation with
hand-crafted payload dicts so each KPI branch is exercised in
isolation.
"""

from __future__ import annotations

import math

from iguanatrader.contexts.research.stats import (
    RSI_WINDOW,
    VOL_WINDOW,
    BriefStats,
    compute_stats,
)


def _bars(closes: list[float], *, volumes: list[float] | None = None) -> list[dict[str, object]]:
    """Build an OHLCV bar list with monotonic dates."""
    if volumes is None:
        volumes = [1_000_000.0] * len(closes)
    return [
        {
            "date": f"2026-01-{i + 1:02d}",
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": vol,
        }
        for i, (close, vol) in enumerate(zip(closes, volumes, strict=True))
    ]


def _payload(
    closes: list[float], *, volumes: list[float] | None = None
) -> dict[str, object]:
    return {"bars": _bars(closes, volumes=volumes), "symbol": "TEST"}


def test_compute_stats_none_when_no_inputs() -> None:
    stats = compute_stats(
        symbol="AMD",
        prices_payload=None,
        benchmark_payload=None,
        fundamentals_payload=None,
        analyst_payload=None,
    )
    assert isinstance(stats, BriefStats)
    assert stats.symbol == "AMD"
    assert stats.last_price is None
    assert stats.rsi_14 is None
    assert stats.forward_pe is None
    assert stats.analyst_target_price is None


def test_last_price_and_day_change_pct() -> None:
    stats = compute_stats(
        symbol="X",
        prices_payload=_payload([100.0, 102.0]),
        benchmark_payload=None,
        fundamentals_payload=None,
        analyst_payload=None,
    )
    assert stats.last_price == 102.0
    assert math.isclose(stats.day_change_pct or 0.0, 2.0, abs_tol=1e-6)


def test_52_week_range_and_position() -> None:
    closes = [100.0, 90.0, 110.0, 105.0]
    stats = compute_stats(
        symbol="X",
        prices_payload=_payload(closes),
        benchmark_payload=None,
        fundamentals_payload=None,
        analyst_payload=None,
    )
    assert stats.high_52w == 110.0
    assert stats.low_52w == 90.0
    # last 105 sits at 75% of the 90→110 range.
    assert math.isclose(stats.position_in_52w_pct or 0.0, 75.0, abs_tol=1e-6)


def test_avg_volume_20d() -> None:
    closes = [100.0] * 25
    volumes = [100_000.0] * 25
    stats = compute_stats(
        symbol="X",
        prices_payload=_payload(closes, volumes=volumes),
        benchmark_payload=None,
        fundamentals_payload=None,
        analyst_payload=None,
    )
    assert stats.avg_volume_20d == 100_000.0


def test_volatility_annualised_zero_when_flat() -> None:
    closes = [100.0] * (VOL_WINDOW + 5)
    stats = compute_stats(
        symbol="X",
        prices_payload=_payload(closes),
        benchmark_payload=None,
        fundamentals_payload=None,
        analyst_payload=None,
    )
    assert stats.volatility_20d_annualized == 0.0


def test_rsi_at_100_when_only_gains() -> None:
    closes = [100.0 + i for i in range(RSI_WINDOW + 5)]
    stats = compute_stats(
        symbol="X",
        prices_payload=_payload(closes),
        benchmark_payload=None,
        fundamentals_payload=None,
        analyst_payload=None,
    )
    # Wilder's RSI: pure-up series → no down moves → RSI = 100.
    assert stats.rsi_14 == 100.0


def test_sma_50_and_position() -> None:
    closes = [100.0] * 49 + [110.0]
    stats = compute_stats(
        symbol="X",
        prices_payload=_payload(closes),
        benchmark_payload=None,
        fundamentals_payload=None,
        analyst_payload=None,
    )
    # SMA50 = (49*100 + 110) / 50 = 100.2; pos = (110 - 100.2)/100.2 * 100 ≈ 9.78%
    assert stats.sma_50 is not None
    assert math.isclose(stats.sma_50, 100.2, abs_tol=1e-6)
    assert stats.pos_vs_sma_50_pct is not None
    assert stats.pos_vs_sma_50_pct > 9.5


def test_relative_strength_vs_benchmark() -> None:
    asset_closes = [100.0] * 253
    asset_closes[-1] = 130.0  # +30% over the trailing 252 bars
    bench_closes = [100.0] * 253
    bench_closes[-1] = 115.0  # +15%
    stats = compute_stats(
        symbol="X",
        prices_payload=_payload(asset_closes),
        benchmark_payload=_payload(bench_closes),
        fundamentals_payload=None,
        analyst_payload=None,
    )
    assert stats.return_12m_pct is not None and math.isclose(
        stats.return_12m_pct, 30.0, abs_tol=1e-6
    )
    # rel_12m = asset 30% - benchmark 15% = +15pp.
    assert stats.relative_strength_vs_spy_12m_pct is not None
    assert math.isclose(stats.relative_strength_vs_spy_12m_pct, 15.0, abs_tol=1e-6)


def test_valuation_from_fundamentals_payload() -> None:
    stats = compute_stats(
        symbol="X",
        prices_payload=None,
        benchmark_payload=None,
        fundamentals_payload={
            "forward_pe": 28.4,
            "pe_ratio": 32.7,
            "price_to_book": 10.5,
            "market_cap": 4.2e12,
        },
        analyst_payload=None,
    )
    assert stats.forward_pe == 28.4
    assert stats.pe_ratio == 32.7
    assert stats.price_to_book == 10.5
    assert stats.market_cap == 4.2e12


def test_analyst_block_upside() -> None:
    stats = compute_stats(
        symbol="X",
        prices_payload=_payload([100.0, 100.0]),
        benchmark_payload=None,
        fundamentals_payload=None,
        analyst_payload={
            "analyst_target_price": 120.0,
            "analyst_count": 25,
        },
    )
    assert stats.analyst_target_price == 120.0
    assert stats.analyst_count == 25
    # upside = (120 - 100)/100 = 20%
    assert math.isclose(stats.upside_to_target_pct or 0.0, 20.0, abs_tol=1e-6)


def test_analyst_block_falls_back_to_alt_keys() -> None:
    stats = compute_stats(
        symbol="X",
        prices_payload=_payload([100.0, 100.0]),
        benchmark_payload=None,
        fundamentals_payload=None,
        analyst_payload={
            "target_price": 90.0,
            "number_of_analysts": 12,
        },
    )
    assert stats.analyst_target_price == 90.0
    assert stats.analyst_count == 12
    assert math.isclose(stats.upside_to_target_pct or 0.0, -10.0, abs_tol=1e-6)
