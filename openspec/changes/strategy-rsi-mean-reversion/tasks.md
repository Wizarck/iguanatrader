# Tasks: strategy-rsi-mean-reversion

- [ ] 1. `apps/api/src/iguanatrader/contexts/trading/strategies/rsi_mean_reversion.py` — new module with `RSIMeanReversionStrategy(Strategy)`, default param constants (`DEFAULT_RSI_PERIOD=14`, `DEFAULT_OVERSOLD=30`, `DEFAULT_OVERBOUGHT=70`, `DEFAULT_ATR_PERIOD=14`, `DEFAULT_ATR_MULT=2.0`, `DEFAULT_RISK_PCT=0.01`, `DEFAULT_EQUITY=10000`), `_compute_rsi_series` helper (Wilder smoothing), local `_compute_atr` copy (mark `# TODO(strategies-indicators-shared)`), `_to_decimal` helper. Long-only cross-UP-from-oversold pattern per proposal.
- [ ] 2. `apps/api/src/iguanatrader/contexts/trading/strategies/manager.py::STRATEGY_REGISTRY` — add line `"rsi_mean_reversion": RSIMeanReversionStrategy,`.
- [ ] 3. `apps/api/src/iguanatrader/contexts/trading/strategies/__init__.py` — import + export `RSIMeanReversionStrategy`; alphabetise `__all__`.
- [ ] 4. `apps/api/tests/unit/contexts/trading/strategies/test_rsi_mean_reversion.py` — 7 unit tests per proposal (cross-up emits, flat no-signal, still-below no-signal, avg_loss_zero, history-too-short, stop-below-entry, position-size).
- [ ] 5. Local scoped lint: ruff + black + mypy --strict on touched files.
- [ ] 6. Run pytest on `apps/api/tests/unit/contexts/trading/strategies/test_rsi_mean_reversion.py` + `apps/api/tests/property/test_strategy_no_lookahead.py` (must still pass with 3 registered strategies).
- [ ] 7. Push + open PR with §4.5.5 + §4.5.6 contract (STOP after gh pr create + canonical AI-reviewer signoff block).
- [ ] 8. STOP after `gh pr create` returns the PR URL. Parent monitors CI.
