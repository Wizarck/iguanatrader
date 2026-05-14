# Tasks: chore-hoist-strategy-indicators

- [ ] 1. Create `apps/api/src/iguanatrader/contexts/trading/strategies/_indicators.py` with `compute_atr` (drop leading underscore — now public to other strategy modules).
- [ ] 2. `apps/api/src/iguanatrader/contexts/trading/strategies/donchian_atr.py` — import `compute_atr`, replace call site, delete local `_compute_atr` definition.
- [ ] 3. `apps/api/src/iguanatrader/contexts/trading/strategies/rsi_mean_reversion.py` — import `compute_atr`, replace call site, delete local `_compute_atr` + forward-pointer comment.
- [ ] 4. `apps/api/src/iguanatrader/contexts/trading/strategies/bollinger_breakout.py` — import `compute_atr`, replace call site, delete local `_compute_atr` + forward-pointer comment.
- [ ] 5. Local scoped lint: ruff + black + mypy --strict on the 4 touched files.
- [ ] 6. Run `pytest apps/api/tests/unit/contexts/trading/strategies/ apps/api/tests/property/test_strategy_no_lookahead.py` — must pass.
- [ ] 7. Push + open PR with §4.5.5 + §4.5.6 contract (STOP + canonical block).
- [ ] 8. STOP after `gh pr create` returns the PR URL.
