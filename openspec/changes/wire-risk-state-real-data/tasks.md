# Tasks: wire-risk-state-real-data

- [ ] 1. **PREREQUISITE check** — confirm `Trade.exit_reason` + `Trade.realised_pnl` columns exist on `main` (via `trades-add-exit-and-realised-pnl-columns` slice merged). If absent, surface `blocked: needs trades-add-exit-and-realised-pnl-columns` and STOP.
- [ ] 2. `apps/api/src/iguanatrader/contexts/risk/repository.py::RiskRepository.load_risk_state` — replace placeholder with composed reads per proposal. Add 6 helper methods (`_count_open_trades`, `_load_latest_equity`, `_load_peak_equity`, `_sum_realised_pnl_since`, `_count_recent_stoplosses`, `_seconds_since_last_close_by_symbol`).
- [ ] 3. Drop the placeholder docstring; replace with real-implementation docstring noting the equity-snapshot-daemon dependency (graceful degradation).
- [ ] 4. `apps/api/tests/integration/test_risk_repository_load_state.py` — 10 integration tests per proposal §"Tests".
- [ ] 5. Scoped lint: ruff + black + mypy --strict on `repository.py` + new test file.
- [ ] 6. Run `pytest apps/api/tests/integration/test_risk_repository_load_state.py apps/api/tests/unit/contexts/risk/`. Verify existing tests pass + new tests green.
- [ ] 7. Verify `test_engine_purity.py` still passes (unchanged — repository changes don't affect engine purity).
- [ ] 8. Push + open PR with §4.5 self-review + canonical AI-reviewer signoff block.
- [ ] 9. STOP after `gh pr create`. Parent monitors CI.
- [ ] 10. Post-merge: update memory file `project_risk_state_placeholder.md` — mark as RESOLVED.
