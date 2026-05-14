# Tasks: fix-donchian-channel-bounds

- [ ] 1. `apps/api/src/iguanatrader/contexts/trading/strategies/donchian_atr.py:74` — change `bars[-lookback:]` to `bars[-lookback-1:-1]`. Update inline docstring to clarify "EXCLUDING the current bar".
- [ ] 2. `apps/api/tests/unit/contexts/trading/strategies/test_donchian_atr.py::_ramp_history` — move spike from `i == n - 1` to `i == n - 2` so wrapper truncation leaves the breakout as `bars[-1]`.
- [ ] 3. Same test file — simplify `test_donchian_emits_proposal_on_breakout` by dropping the `extra_bar` hack (now redundant with fix + helper refactor).
- [ ] 4. Same test file — add 1 new regression test `test_donchian_no_signal_when_close_below_channel` covering the flat-ramp no-breakout case explicitly.
- [ ] 5. Local scoped lint: ruff + black + mypy --strict on touched files.
- [ ] 6. Local pytest on `apps/api/tests/unit/contexts/trading/strategies/test_donchian_atr.py` + `tests/property/test_strategy_no_lookahead.py` — all green (4-5 tests in donchian + property test still passes).
- [ ] 7. Push + open PR with §4.5 self-review + canonical AI-reviewer signoff block.
- [ ] 8. STOP after `gh pr create`. Parent monitors CI.
