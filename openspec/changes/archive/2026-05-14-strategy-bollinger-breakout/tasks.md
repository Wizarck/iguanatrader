# Tasks: strategy-bollinger-breakout

- [ ] 1. `apps/api/src/iguanatrader/contexts/trading/strategies/bollinger_breakout.py` — new module with `BollingerBreakoutStrategy(Strategy)`, default constants per proposal (`DEFAULT_PERIOD=20`, `DEFAULT_NUM_STD=2.0`, `DEFAULT_SQUEEZE_THRESHOLD=None`, `DEFAULT_SQUEEZE_LOOKBACK=6`, `DEFAULT_ATR_PERIOD=14`, `DEFAULT_ATR_MULT=2.0`, `DEFAULT_RISK_PCT=0.01`, `DEFAULT_EQUITY=10000`), `_compute_bollinger_bands` helper (SMA + stdev → bands), optional squeeze filter, local `_compute_atr` copy with `# TODO(strategies-indicators-shared)`, `_to_decimal` helper.
- [ ] 2. `apps/api/src/iguanatrader/contexts/trading/strategies/manager.py::STRATEGY_REGISTRY` — add line `"bollinger_breakout": BollingerBreakoutStrategy,`.
- [ ] 3. `apps/api/src/iguanatrader/contexts/trading/strategies/__init__.py` — import + export `BollingerBreakoutStrategy`; alphabetise `__all__`.
- [ ] 4. `apps/api/tests/unit/contexts/trading/strategies/test_bollinger_breakout.py` — 6 unit tests per proposal §Tests.
- [ ] 5. Local scoped lint: ruff + black + mypy --strict on touched files.
- [ ] 6. Run pytest on the new test file + property-based `test_strategy_no_lookahead.py` (must pass with 4 strategies registered).
- [ ] 7. Push + open PR with §4.5.5 + §4.5.6 contract (STOP after gh pr create + canonical AI-reviewer signoff block).
- [ ] 8. STOP after `gh pr create` returns the PR URL. Parent monitors CI.
