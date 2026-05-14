# Proposal: strategy-volume-donchian

> **Add the v1.5 `volume_donchian` strategy** — DonchianATR breakout with an additional volume-anomaly filter (only emit signal when current bar's volume exceeds a multiple of the trailing average volume). Same long-entry / ATR-stop / risk-pct mechanics as `donchian_atr`, plus a volume conviction gate. Slots into the existing `Strategy` ABC + `STRATEGY_REGISTRY` pattern.

## Why

`docs/backlog.md` v1.5 §Estrategias adicionales lists "Volume-weighted Donchian" as the 4th and final v1.5 strategy. Operators get a stricter Donchian variant: rather than fire on every channel break, only fire when volume confirms "real" breakouts (institutional buying) vs noise. Backtests typically show ~30-50% fewer signals than vanilla Donchian but with materially better win rate.

The filter is a simple ratio test: `volume[now] > volume_threshold * avg(volume[-vol_window:-1])`. Both `vol_window` and `volume_threshold` are configurable.

## What

### New module

`apps/api/src/iguanatrader/contexts/trading/strategies/volume_donchian.py` — `VolumeDonchianStrategy(Strategy)`:

```python
class VolumeDonchianStrategy(Strategy):
    def name(self) -> str:
        return "volume_donchian"

    def version(self) -> str:
        return "0.1.0"

    @property
    def MIN_BARS(self) -> int:
        return max(DEFAULT_PERIOD, DEFAULT_VOL_WINDOW) + DEFAULT_ATR_PERIOD + 2

    def _compute_signal_impl(...) -> Proposal | None:
        # 1. Same Donchian high check: closes[-1] > max(high[-period-1:-1]).
        # 2. Volume gate: volume[-1] > volume_threshold * mean(volume[-vol_window-1:-1]).
        # 3. ATR-based stop; risk-pct sizing.
        # 4. Return long Proposal; reasoning dict includes volume_ratio.
```

### Defaults (overridable via `StrategyConfigSnapshot.params`)

- `period` = 20 (Donchian canonical default)
- `vol_window` = 20 (trailing volume average window)
- `volume_threshold` = 1.5 (current bar volume must be ≥ 1.5× trailing average to fire)
- `atr_period` = 14
- `atr_mult` = 2.0
- `risk_pct` = 0.01
- `equity` = 10_000

### Registry wiring

`apps/api/src/iguanatrader/contexts/trading/strategies/manager.py::STRATEGY_REGISTRY` — add:

```python
"volume_donchian": VolumeDonchianStrategy,
```

`apps/api/src/iguanatrader/contexts/trading/strategies/__init__.py` — add export.

### Tests

`apps/api/tests/unit/contexts/trading/strategies/test_volume_donchian.py`:

1. `test_volume_donchian_emits_on_breakout_with_volume` — channel break AND volume[-1] = 2× avg → Proposal emitted.
2. `test_volume_donchian_no_signal_when_volume_insufficient` — channel break BUT volume[-1] = 1× avg → no signal.
3. `test_volume_donchian_no_signal_when_no_breakout` — flat history → no signal.
4. `test_volume_donchian_threshold_param_overridable` — `volume_threshold=2.0` rejects 1.5× volume that would pass at default.
5. `test_volume_donchian_no_signal_when_history_too_short` — < MIN_BARS → None.
6. `test_volume_donchian_stop_below_entry` — ATR stop sanity.
7. `test_volume_donchian_position_size_respects_risk_pct` — quantity formula.
8. `test_volume_donchian_reasoning_includes_volume_ratio` — `reasoning["volume_ratio"]` populated.

Property test `tests/property/test_strategy_no_lookahead.py` auto-covers no-lookahead via registry iteration.

### Reasoning dict shape

```json
{
  "strategy": "volume_donchian",
  "period": 20,
  "vol_window": 20,
  "volume_threshold": "1.5",
  "donchian_high": "105.20",
  "current_close": "106.50",
  "current_volume": "1500000",
  "avg_volume": "850000",
  "volume_ratio": "1.76",
  "atr": "1.85",
  "atr_mult": "2.0",
  "risk_pct": "0.01",
  "equity": "10000",
  "entry": "106.50",
  "stop": "102.80",
  "computed_at": "2026-05-14T..."
}
```

### `_compute_atr` reuse

By the time this slice ships, the v1.5 strategy wave will have 4-5 ATR callers (Donchian, RSI, Bollinger, MACD, this). The `strategies-indicators-shared` hoist should already exist (introduced by `strategy-macd-cross` slice per its proposal §"_compute_atr reuse"). This slice imports from `_indicators.py`. If the hoist hasn't happened yet (e.g., because this slice ships first), copy-paste + TODO comment.

## Out of scope

- **Short side** — long-only per v1.5 backlog.
- **Adaptive volume threshold** — could auto-tune `volume_threshold` based on symbol volatility regime. v2 ML extension.
- **Per-bar volume model** — current logic treats volume as a simple ratio; sophisticated models (VPIN, order-flow imbalance) are v3 (institutional features).
- **Stub-out vanilla DonchianATR when this strategy is enabled per symbol** — both can coexist on different symbols per ADR-008. If a symbol is configured for both simultaneously, both fire independently (risk engine handles dedup).

## Acceptance

- `STRATEGY_REGISTRY` contains the new entry (catalogue now: donchian_atr, sma_cross, rsi_mean_reversion, bollinger_breakout, macd_cross, volume_donchian — 6 entries).
- 8 new unit tests pass.
- `test_strategy_no_lookahead.py` passes (auto-coverage).
- mypy --strict clean.
- ruff + black clean.
- `config/strategies.yaml` can immediately reference `strategy: volume_donchian`.
