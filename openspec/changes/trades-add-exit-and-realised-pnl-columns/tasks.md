# Tasks: trades-add-exit-and-realised-pnl-columns

- [ ] 1. `apps/api/src/iguanatrader/migrations/versions/0015_trade_exit_columns.py` — new Alembic migration: add `exit_reason TEXT NULL` + `realised_pnl NUMERIC(18,8) NULL` to `trades`. Add CHECK constraint for exit_reason values.
- [ ] 2. `apps/api/src/iguanatrader/contexts/trading/models.py::Trade` — declare new ORM columns. Extend `__append_only_mutable_columns__` frozenset to include them.
- [ ] 3. `apps/api/tests/integration/persistence/test_trades_append_only.py` (or new file) — 1 test verifying mutability whitelist permits updates on the new columns.
- [ ] 4. Migration smoke test — verify `alembic upgrade head` applies cleanly + downgrade reverses it. (May already be covered by existing migration smoke; if so, just confirm.)
- [ ] 5. Scoped lint: ruff + black + mypy --strict on touched files.
- [ ] 6. Run `pytest` on touched test files + migration smoke + any test_trades_* files to confirm no regressions.
- [ ] 7. Push + open PR with §4.5 self-review + canonical AI-reviewer signoff block.
- [ ] 8. STOP after `gh pr create`. Parent monitors CI.
