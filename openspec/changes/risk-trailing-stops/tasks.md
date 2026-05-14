# Tasks: risk-trailing-stops

- [ ] 1. `apps/api/src/iguanatrader/contexts/risk/stop_management.py` — new module per proposal: `TrailingStopUpdate` dataclass + `compute_trailing_stop` pure function with long-side logic + sell-side branch (untested in v1.5).
- [ ] 2. `apps/api/src/iguanatrader/contexts/risk/models.py` — extend `RiskCaps` (`trail_trigger_pct: Decimal | None`, `trail_atr_mult: Decimal = Decimal("1.5")`, `trail_atr_period: int = 14`).
- [ ] 3. `apps/api/tests/unit/contexts/risk/test_stop_management.py` — 6 tests per proposal.
- [ ] 4. Local scoped lint: ruff + black + mypy --strict on touched files.
- [ ] 5. Run `pytest tests/unit/contexts/risk/test_stop_management.py` — green.
- [ ] 6. Push + open PR with §4.5 self-review + canonical AI-reviewer signoff block.
- [ ] 7. STOP after `gh pr create`. Parent monitors CI.
- [ ] 8. After merge: queue follow-up slice `orchestration-trailing-stops-cron` (NOT shipped in this slice).
