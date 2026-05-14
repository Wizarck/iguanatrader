# Proposal: strategy-macd-cross

> **Add the v1.5 `macd_cross` strategy** — Moving Average Convergence Divergence (MACD) signal-line cross-up long entry with ATR-based stop + risk-pct sizing. Momentum-based complement to the trend-following pair (DonchianATR breakout + SMA cross) and the counter-trend RSI mean-reversion. Slots into the existing `Strategy` ABC + `STRATEGY_REGISTRY` pattern.

## Why

`docs/backlog.md` v1.5 §Estrategias adicionales lists MACD crossover as the canonical momentum strategy for retail equity. MACD captures medium-term momentum shifts that simple SMA cross misses: the histogram (MACD – signal) leads SMA cross by 5-10 bars when momentum is decelerating. Operators get a third trend-regime signal alongside Donchian breakout (channel) and SMA cross (long-MA cross).

The cross-up condition is well-understood: `MACD[t-1] <= signal[t-1] AND MACD[t] > signal[t]`. Standard parameters (fast=12, slow=26, signal=9) are the Appel canonical defaults.

## What

### New module

`apps/api/src/iguanatrader/contexts/trading/strategies/macd_cross.py` — `MACDCrossStrategy(Strategy)`:

```python
class MACDCrossStrategy(Strategy):
    def name(self) -> str:
        return "macd_cross"

    def version(self) -> str:
        return "0.1.0"

    @property
    def MIN_BARS(self) -> int:
        return DEFAULT_SLOW + DEFAULT_SIGNAL + DEFAULT_ATR_PERIOD + 2

    def _compute_signal_impl(...) -> Proposal | None:
        # 1. Compute EMA(fast) and EMA(slow) over closes.
        # 2. MACD = EMA(fast) - EMA(slow); track series for signal smoothing.
        # 3. signal_line = EMA(signal) of MACD series.
        # 4. Cross-up: macd[t-1] <= signal[t-1] AND macd[t] > signal[t].
        # 5. Optional: require macd > 0 OR macd < 0 (configurable bias filter).
        # 6. ATR-based stop; risk-pct sizing.
        # 7. Return long Proposal with reasoning dict.
```

### Defaults (overridable via `StrategyConfigSnapshot.params`)

- `fast` = 12 (Appel canonical)
- `slow` = 26
- `signal` = 9
- `bias_filter` = None (no MACD-zero filter; set to "positive" to require macd > 0 OR "negative" to require macd < 0 at cross)
- `atr_period` = 14
- `atr_mult` = 2.0
- `risk_pct` = 0.01
- `equity` = 10_000

### Registry wiring

`apps/api/src/iguanatrader/contexts/trading/strategies/manager.py::STRATEGY_REGISTRY` — add one line:

```python
"macd_cross": MACDCrossStrategy,
```

`apps/api/src/iguanatrader/contexts/trading/strategies/__init__.py` — add `MACDCrossStrategy` to exports + `__all__`.

### EMA computation

Canonical formula:
1. Initial EMA: simple mean of the first `period` closes.
2. Subsequent: `EMA[t] = close[t] * k + EMA[t-1] * (1 - k)` where `k = 2 / (period + 1)`.

For MACD computation:
- `ema_fast_series` over closes (length matches closes after warmup).
- `ema_slow_series` over closes.
- `macd_series[t] = ema_fast[t] - ema_slow[t]` (only defined where both EMAs are warm).
- `signal_series[t]` = EMA(signal_period) of macd_series (warmup adds another `signal_period - 1` bars).

Return `(macd_prev, macd_now, signal_prev, signal_now)` for the cross check.

### Tests

`apps/api/tests/unit/contexts/trading/strategies/test_macd_cross.py`:

1. `test_macd_emits_proposal_on_cross_up` — synthetic history with engineered MACD cross-up at the latest bar — assert `Proposal.side == "buy"`, `Proposal.reasoning["strategy"] == "macd_cross"`.
2. `test_macd_no_signal_when_no_cross` — flat history, no momentum shift — assert None.
3. `test_macd_no_signal_when_cross_down` — engineered cross-down (MACD falls below signal) — assert None (long-only).
4. `test_macd_bias_filter_blocks_negative_cross` — `bias_filter="positive"` + cross-up with macd < 0 — assert None.
5. `test_macd_bias_filter_allows_positive_cross` — `bias_filter="positive"` + cross-up with macd > 0 — assert Proposal.
6. `test_macd_no_signal_when_history_too_short` — < MIN_BARS — assert None.
7. `test_macd_stop_below_entry` — ATR-derived stop sanity.
8. `test_macd_position_size_respects_risk_pct` — quantity formula.

Property-based test `tests/property/test_strategy_no_lookahead.py` auto-covers the no-lookahead invariant via `STRATEGY_REGISTRY` iteration.

### Reasoning dict shape

```json
{
  "strategy": "macd_cross",
  "fast": 12,
  "slow": 26,
  "signal": 9,
  "macd_prev": "-0.150",
  "macd_now": "0.025",
  "signal_prev": "-0.080",
  "signal_now": "-0.012",
  "atr": "1.85",
  "atr_mult": "2.0",
  "risk_pct": "0.01",
  "equity": "10000",
  "entry": "100.50",
  "stop": "96.80",
  "computed_at": "2026-05-14T..."
}
```

Decimals serialised as strings (Pydantic v2 default).

### `_compute_atr` reuse

Per the `strategy-rsi-mean-reversion` proposal decision A (copy-paste tolerated up to 3rd duplication), this would be the 4th caller (donchian_atr, rsi_mean_reversion, bollinger_breakout, macd_cross). **Decision: HOIST.** Extract `_compute_atr` to `apps/api/src/iguanatrader/contexts/trading/strategies/_indicators.py` as part of this slice. Update donchian_atr.py + rsi_mean_reversion.py + bollinger_breakout.py to import from `_indicators`. The hoist is mechanical (15-line copy → import) and avoids 4-way drift.

If hoist creates merge friction with parallel in-flight strategy slices (RSI / Bollinger), defer hoist to a follow-up `strategies-indicators-shared` chore slice and copy-paste here too. Recommendation: hoist only AFTER RSI + Bollinger PRs merge.

## Out of scope

- **Short side** — long-only per v1.5 backlog. MACD cross-down as exit signal is v2 (with `evaluate_exit` method).
- **MACD histogram divergence** — divergence detection (price makes higher high, MACD makes lower high) is a richer signal but adds a phase-detection layer. v2.
- **Multi-timeframe MACD confluence** — defer to v2 `multi-timeframe-trend-following` slice.
- **Auto-tuned (fast, slow, signal)** — current defaults match Appel canonical; per-symbol tuning is `config/strategies.yaml` concern.

## Acceptance

- `STRATEGY_REGISTRY` contains the new entry (count ≥ 4 after this + prior strategies merge).
- 8 new unit tests pass.
- `test_strategy_no_lookahead.py` passes (auto-coverage).
- mypy --strict clean.
- ruff + black clean.
- `config/strategies.yaml` mapping can immediately reference `strategy: macd_cross`.
