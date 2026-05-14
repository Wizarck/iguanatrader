# Tasks: risk-stoploss-guard

- [ ] 1. **PREREQUISITE check** — confirm `Trade.exit_reason` column exists in models + has migration. If absent, this slice depends on a chore-add-exit-reason-column predecessor. Surface as `blocked: ...` if missing.
- [ ] 2. `apps/api/src/iguanatrader/contexts/risk/protections/stoploss_guard.py` — new module per proposal.
- [ ] 3. `apps/api/src/iguanatrader/contexts/risk/models.py` — extend `RiskCaps` (`stoploss_guard_threshold: int | None`, `stoploss_guard_lookback: int = 5`) + `RiskState` (`recent_stoploss_count_trailing: int = 0`, `recent_trades_lookback: int = 0`).
- [ ] 4. `apps/api/src/iguanatrader/contexts/risk/service.py::_build_state` — query trailing closed trades, count `exit_reason == "stop"`, populate state.
- [ ] 5. `apps/api/src/iguanatrader/contexts/risk/engine.py::_PROTECTIONS` — append `stoploss_guard.evaluate`.
- [ ] 6. `apps/api/tests/unit/contexts/risk/protections/test_stoploss_guard.py` — 4 tests.
- [ ] 7. `apps/api/tests/integration/test_risk_service.py` — 1 new test for state derivation.
- [ ] 8. Local scoped lint: ruff + black + mypy --strict on touched files.
- [ ] 9. Run `pytest tests/unit/contexts/risk/ tests/integration/test_risk_service.py` — green.
- [ ] 10. Push + open PR with §4.5 self-review + canonical AI-reviewer signoff block (paraphrase any pending-marker prose per ai-playbook STUB_INDICATORS gotcha).
- [ ] 11. STOP after `gh pr create`. Parent monitors CI.
