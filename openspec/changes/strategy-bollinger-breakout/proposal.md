# Proposal: strategy-bollinger-breakout

> **Add the v1.5 `bollinger_breakout` strategy** — SMA(20) ± 2σ band breakout long entry with ATR-based stop + risk-pct sizing. Volatility-based complement to the channel-based `DonchianATR` breakout. Slots into the existing `Strategy` ABC + `STRATEGY_REGISTRY` pattern.

## Why

`docs/backlog.md` v1.5 lists "Bollinger Bands breakout/squeeze (vol-based)" alongside RSI / MACD / Volume-Donchian. Operators get a second trend-following signal that adapts entry threshold to recent volatility (unlike Donchian which uses raw high-of-N). On a quiet equity (low recent stdev) the upper band sits closer to price → earlier breakout signal; on a noisy equity it sits further → later but more conviction.

The "squeeze filter" optional param adds confluence: only emit breakout when recent bandwidth was compressed (consolidation phase) → captures the canonical "breakout from low-volatility regime" setup that retail traders chase.

## What

### New module

`apps/api/src/iguanatrader/contexts/trading/strategies/bollinger_breakout.py` — `BollingerBreakoutStrategy(Strategy)`:

```python
class BollingerBreakoutStrategy(Strategy):
    def name(self) -> str:
        return "bollinger_breakout"

    def version(self) -> str:
        return "0.1.0"

    @property
    def MIN_BARS(self) -> int:
        return DEFAULT_PERIOD + DEFAULT_ATR_PERIOD + 2  # wrapper drops bars[-1]

    def _compute_signal_impl(...) -> Proposal | None:
        # 1. Compute SMA(period) + stdev(period) over closes.
        # 2. upper_band = sma + num_std * stdev; lower_band = sma - num_std * stdev.
        # 3. Breakout test: closes[-1] > upper_band.
        # 4. Optional squeeze filter: bandwidth = (upper - lower) / sma; require bandwidth < squeeze_threshold over previous N bars.
        # 5. ATR-based stop; risk-pct sizing.
        # 6. Return long Proposal with reasoning dict.
```

### Defaults (overridable via `StrategyConfigSnapshot.params`)

- `period` = 20 (canonical Bollinger default)
- `num_std` = 2.0
- `squeeze_threshold` = None (squeeze filter disabled by default; set to e.g. 0.05 to require bandwidth < 5% of SMA over prior N bars before signal)
- `squeeze_lookback` = 6 (how many recent bars must show compressed bandwidth)
- `atr_period` = 14
- `atr_mult` = 2.0
- `risk_pct` = 0.01
- `equity` = 10_000

### Registry wiring

`apps/api/src/iguanatrader/contexts/trading/strategies/manager.py::STRATEGY_REGISTRY` — add `"bollinger_breakout": BollingerBreakoutStrategy,`.

`apps/api/src/iguanatrader/contexts/trading/strategies/__init__.py` — import + export.

### `_compute_atr` reuse — 3rd caller triggers hoist decision

After this slice lands, `_compute_atr` exists in:
1. `donchian_atr.py` (original)
2. `rsi_mean_reversion.py` (copied in v1.5 slice 1, with `# TODO(strategies-indicators-shared)` comment)
3. `bollinger_breakout.py` (this slice — copy with the same TODO)

**Decision**: still copy. The TODO comment now appears 3 times. Hoisting to `_indicators.py` is the natural follow-up after this slice; queue it as a `chore-hoist-strategy-indicators` slice before slice 4 (MACD) lands. If MACD doesn't need ATR, defer the hoist until a 4th caller emerges.

### Tests

`apps/api/tests/unit/contexts/trading/strategies/test_bollinger_breakout.py` — 6 new tests:

1. `test_bollinger_emits_proposal_on_breakout_above_upper_band` — synthetic history where closes rise above SMA + 2σ.
2. `test_bollinger_no_signal_when_close_within_band` — flat history.
3. `test_bollinger_no_signal_when_only_touches_upper_band` — close == upper exactly, must be strictly >.
4. `test_bollinger_no_signal_when_squeeze_filter_active_and_bandwidth_too_wide` — `squeeze_threshold=0.05`, recent bars have wide bandwidth → no signal even on breakout.
5. `test_bollinger_emits_proposal_when_squeeze_filter_active_and_bandwidth_compressed` — `squeeze_threshold=0.05`, recent bars compressed → signal fires on breakout.
6. `test_bollinger_position_size_respects_risk_pct` — quantity = (risk_pct * equity) / (entry - stop).

Plus property-based `test_strategy_no_lookahead.py` auto-covers.

### Reasoning dict

```json
{
  "strategy": "bollinger_breakout",
  "period": 20,
  "num_std": "2.0",
  "sma": "101.20",
  "stdev": "1.50",
  "upper_band": "104.20",
  "lower_band": "98.20",
  "bandwidth_ratio": "0.0593",
  "squeeze_filter_active": false,
  "atr": "1.80",
  "atr_mult": "2.0",
  "risk_pct": "0.01",
  "equity": "10000",
  "entry": "104.50",
  "stop": "100.90",
  "computed_at": "2026-05-14T..."
}
```

## Out of scope

- **Short side (close < lower band)** — v1.5 long-only.
- **Squeeze-only signal (no breakout, just exit-of-compression)** — v1.5.x parameter extension if operators want it.
- **`_indicators.py` hoist** — separately tracked `chore-hoist-strategy-indicators` slice; do not bundle here.
- **Mean-reversion variant (long at lower band)** — RSI mean-reversion already covers the counter-trend pattern; would create overlap.
- **Per-symbol default params** — config concern, not registry.

## Acceptance

- `STRATEGY_REGISTRY` contains `donchian_atr`, `sma_cross`, `rsi_mean_reversion`, `bollinger_breakout`.
- 6 new unit tests pass.
- Property-based no-lookahead test still passes with 4 strategies registered.
- mypy --strict + ruff + black clean.
- Config-yaml consumers can reference `strategy: bollinger_breakout`.
