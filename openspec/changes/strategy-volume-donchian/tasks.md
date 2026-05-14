# Tasks: strategy-volume-donchian

- [ ] 1. `apps/api/src/iguanatrader/contexts/trading/strategies/volume_donchian.py` — implement `VolumeDonchianStrategy(Strategy)` per proposal: Donchian high break + volume-ratio gate, ATR stop, risk-pct sizing.
- [ ] 2. `apps/api/src/iguanatrader/contexts/trading/strategies/manager.py` — add `"volume_donchian": VolumeDonchianStrategy,` + import.
- [ ] 3. `apps/api/src/iguanatrader/contexts/trading/strategies/__init__.py` — export `VolumeDonchianStrategy` + `__all__`.
- [ ] 4. **CONDITIONAL** — if `_indicators.py` already hoisted (post-MACD slice): import `_compute_atr` from there. Else copy-paste + TODO comment.
- [ ] 5. `apps/api/tests/unit/contexts/trading/strategies/test_volume_donchian.py` — 8 tests per proposal.
- [ ] 6. Local scoped lint: ruff + black + mypy --strict on touched files.
- [ ] 7. Run `pytest <test file> apps/api/tests/property/test_strategy_no_lookahead.py` — both pass.
- [ ] 8. Push + open PR with §4.5 self-review + canonical AI-reviewer signoff block.
- [ ] 9. STOP after `gh pr create` returns the PR URL. Parent monitors CI.
