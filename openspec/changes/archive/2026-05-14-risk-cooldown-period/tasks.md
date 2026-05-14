# Tasks: risk-cooldown-period

- [ ] 1. `apps/api/src/iguanatrader/contexts/risk/protections/cooldown_period.py` — new module per proposal.
- [ ] 2. `apps/api/src/iguanatrader/contexts/risk/models.py` — extend `RiskCaps` (`cooldown_seconds: int | None = None`) + `RiskState` (`seconds_since_last_close_by_symbol: dict[str, int] = {}`).
- [ ] 3. `apps/api/src/iguanatrader/contexts/risk/service.py::_build_state` — query last close per symbol + compute seconds_since.
- [ ] 4. `apps/api/src/iguanatrader/contexts/risk/engine.py::_PROTECTIONS` — append `cooldown_period.evaluate`.
- [ ] 5. `apps/api/tests/unit/contexts/risk/protections/test_cooldown_period.py` — 5 tests.
- [ ] 6. `apps/api/tests/integration/test_risk_service.py` — 1 new test for state derivation.
- [ ] 7. Local scoped lint: ruff + black + mypy --strict on touched files.
- [ ] 8. Run `pytest tests/unit/contexts/risk/ tests/integration/test_risk_service.py` — green.
- [ ] 9. Push + open PR with §4.5 self-review + canonical AI-reviewer signoff block.
- [ ] 10. STOP after `gh pr create`. Parent monitors CI.
