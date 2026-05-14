# Proposal: strategy-rsi-mean-reversion

> **Add the v1.5 `rsi_mean_reversion` strategy** — Wilder RSI(14) cross-UP-from-oversold long entry with ATR-based stop + risk-pct sizing. First counter-trend strategy in the catalogue (DonchianATR + SMA Cross are trend-following). Slots into the existing `Strategy` ABC + `STRATEGY_REGISTRY` pattern; no infrastructure changes.

## Why

`docs/backlog.md` v1.5 §Estrategias adicionales lists 4 retail-equity strategies. RSI mean-reversion is the canonical counter-trend complement to the trend-following pair already shipped (DonchianATR breakout + SMA Cross). Operators get a second signal regime: "buy oversold dips" alongside "buy breakouts". Per-symbol config (ADR-008) means a single tenant can run RSI on mean-reverting names (KO, PEP) while running Donchian on trend-following names (TSLA, NVDA).

Risk profile is well-understood: Wilder's RSI is the most-cited oscillator in retail equity; the cross-UP-from-oversold pattern (RSI[prev] < oversold AND RSI[now] ≥ oversold) reduces false positives versus "RSI below threshold = buy" by waiting for the bounce confirmation.

## What

### New module

`apps/api/src/iguanatrader/contexts/trading/strategies/rsi_mean_reversion.py` — `RSIMeanReversionStrategy(Strategy)` implementing the canonical pattern:

```python
class RSIMeanReversionStrategy(Strategy):
    def name(self) -> str:
        return "rsi_mean_reversion"

    def version(self) -> str:
        return "0.1.0"

    @property
    def MIN_BARS(self) -> int:
        # Need rsi_period + 1 for the prev-vs-now cross check, plus atr_period
        # for the stop sizing, plus 1 extra bar (wrapper drops bars[-1]).
        return DEFAULT_RSI_PERIOD + DEFAULT_ATR_PERIOD + 2

    def _compute_signal_impl(...) -> Proposal | None:
        # 1. Compute Wilder RSI series over closes[-(rsi_period + 1):].
        # 2. If RSI[prev] >= oversold OR RSI[now] < oversold → no signal (no cross-UP).
        # 3. Compute ATR(atr_period) over trailing window.
        # 4. entry = closes[-1]; stop = entry - atr_mult * ATR; quantity = risk_pct * equity / (entry - stop).
        # 5. Return long Proposal with reasoning dict (strategy, rsi_now, rsi_prev, oversold, atr, ...).
```

### Defaults (overridable via `StrategyConfigSnapshot.params`)

- `rsi_period` = 14 (Wilder canonical)
- `oversold` = 30
- `overbought` = 70 (informational only; v1.5 is long-only)
- `atr_period` = 14
- `atr_mult` = 2.0
- `risk_pct` = 0.01
- `equity` = 10_000 (fallback when broker equity not yet wired)

### Registry wiring

`apps/api/src/iguanatrader/contexts/trading/strategies/manager.py::STRATEGY_REGISTRY` — add one line:

```python
"rsi_mean_reversion": RSIMeanReversionStrategy,
```

`apps/api/src/iguanatrader/contexts/trading/strategies/__init__.py` — add `RSIMeanReversionStrategy` to exports + `__all__`.

### Wilder RSI computation

Canonical formula:
1. For each pair of consecutive closes, compute `gain = max(0, close[i] - close[i-1])` and `loss = max(0, close[i-1] - close[i])`.
2. Initial `avg_gain` and `avg_loss` = simple mean of the first `rsi_period` gains/losses.
3. Subsequent values: `avg_gain[t] = (avg_gain[t-1] * (rsi_period - 1) + gain[t]) / rsi_period` (Wilder smoothing). Same for `avg_loss`.
4. `RS = avg_gain / avg_loss` (handle `avg_loss == 0` → return RSI = 100 — "perfectly bullish", no signal in mean-reversion).
5. `RSI = 100 - 100 / (1 + RS)`.

Two-value return: `(rsi_prev, rsi_now)` for the cross-check.

### Tests

`apps/api/tests/unit/contexts/trading/strategies/test_rsi_mean_reversion.py` — covering:

1. `test_rsi_emits_proposal_on_cross_up_from_oversold` — synthetic history where RSI drops below 30 then crosses back up. Assert `Proposal.side == "buy"`, `Proposal.reasoning["strategy"] == "rsi_mean_reversion"`.
2. `test_rsi_no_signal_when_not_oversold` — flat history with RSI hovering 50 — assert None.
3. `test_rsi_no_signal_when_still_below_oversold` — RSI[prev]=20, RSI[now]=25 (still below 30, no cross yet) — assert None.
4. `test_rsi_no_signal_when_avg_loss_zero` — strictly rising prices (RS = ∞ → RSI = 100) — assert None.
5. `test_rsi_no_signal_when_history_too_short` — < MIN_BARS — assert None (already covered by wrapper, sanity check).
6. `test_rsi_stop_below_entry` — sanity check that ATR-derived stop < entry (long-only).
7. `test_rsi_position_size_respects_risk_pct` — verify quantity = (risk_pct * equity) / (entry - stop).

Plus the existing property-based test `tests/property/test_strategy_no_lookahead.py` AUTOMATICALLY covers the no-lookahead invariant for any registered strategy (the property test iterates `STRATEGY_REGISTRY`).

### Reasoning dict shape

```json
{
  "strategy": "rsi_mean_reversion",
  "rsi_period": 14,
  "oversold": 30,
  "rsi_prev": "28.5",
  "rsi_now": "32.1",
  "atr": "1.85",
  "atr_mult": "2.0",
  "risk_pct": "0.01",
  "equity": "10000",
  "entry": "100.50",
  "stop": "96.80",
  "computed_at": "2026-05-14T..."
}
```

Decimals serialised as strings (Pydantic v2 default) so the reasoning dict survives JSON round-trip without precision loss.

### `_compute_atr` reuse

`donchian_atr.py::_compute_atr` is module-private. Two options:
- **A. Copy-paste** into `rsi_mean_reversion.py` (3rd duplication tolerated; if a 4th lands, hoist).
- **B. Hoist now** to `apps/api/src/iguanatrader/contexts/trading/strategies/_indicators.py`.

**Decision: A (copy-paste).** Premature abstraction risk. The function is 15 lines; hoisting introduces a new module that 2 strategies use. The 4th strategy (Bollinger or MACD) will land soon and at that point hoisting is justified by 3 callers. For now, keep `donchian_atr._compute_atr` + new `rsi_mean_reversion._compute_atr` as separate copies. Mark with a `# TODO(strategies-indicators-shared): hoist when 3rd caller lands` comment.

## Out of scope

- **Short side (`side == "sell"`)** — long-only per v1.5 backlog. RSI overbought → exit-only signal is v2 (when shorting + exit signals both land).
- **Stoploss customisation** — uses ATR-based stop like Donchian; if operators want %-based stops as an alternative, that's a parameter extension in v1.5.x.
- **`_indicators.py` hoist** — deferred to the 3rd strategy needing ATR (likely `bollinger-breakout` or `volume-donchian` in the same v1.5 wave).
- **Per-symbol default params** — current registry uses class-level defaults; if SPY benefits from `rsi_period=21` while AAPL prefers `rsi_period=14`, that's a `config/strategies.yaml` concern, not a registry concern.
- **Exit signal generation** — current `Strategy.evaluate` returns only entry proposals. Risk engine handles exits (stop hit, daily-loss-cap, manual `/forceexit`). Adding "RSI > overbought → exit existing long" requires a `evaluate_exit` method on the ABC — deferred to v2 strategy-exit-signals slice.

## Acceptance

- `STRATEGY_REGISTRY` contains 3 entries: `donchian_atr`, `sma_cross`, `rsi_mean_reversion`.
- `pytest apps/api/tests/unit/contexts/trading/strategies/test_rsi_mean_reversion.py` — 7 new tests pass.
- `pytest apps/api/tests/property/test_strategy_no_lookahead.py` — still passes (auto-covers new strategy via registry iteration).
- `mypy --strict` clean on the new module.
- `ruff` + `black` clean.
- Adopting consumers (`config/strategies.yaml` per-symbol mapping) can immediately reference `strategy: rsi_mean_reversion` in their config.
