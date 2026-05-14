# Tasks: strategy-macd-cross

- [ ] 1. `apps/api/src/iguanatrader/contexts/trading/strategies/macd_cross.py` — implement `MACDCrossStrategy(Strategy)` per proposal: Wilder/Appel canonical EMA + MACD + signal line, cross-up entry, ATR stop, risk-pct sizing.
- [ ] 2. `apps/api/src/iguanatrader/contexts/trading/strategies/manager.py` — add `"macd_cross": MACDCrossStrategy,` to `STRATEGY_REGISTRY` + import.
- [ ] 3. `apps/api/src/iguanatrader/contexts/trading/strategies/__init__.py` — export `MACDCrossStrategy` + `__all__`.
- [ ] 4. **CONDITIONAL** — if RSI + Bollinger PRs already merged at slice start: hoist `_compute_atr` to `_indicators.py` + update donchian_atr.py + rsi_mean_reversion.py + bollinger_breakout.py imports. Else copy-paste ATR helper into macd_cross.py + add TODO comment.
- [ ] 5. `apps/api/tests/unit/contexts/trading/strategies/test_macd_cross.py` — 8 tests per proposal.
- [ ] 6. Local scoped lint: ruff + black + mypy --strict on touched files.
- [ ] 7. Run `pytest <test file> apps/api/tests/property/test_strategy_no_lookahead.py` — both pass.
- [ ] 8. Push + open PR with §4.5 self-review + canonical AI-reviewer signoff block (per ai-playbook v0.13.4 §4.5.6).
- [ ] 9. STOP after `gh pr create` returns the PR URL. Parent monitors CI (per ai-playbook v0.13.4 §4.5.5).
