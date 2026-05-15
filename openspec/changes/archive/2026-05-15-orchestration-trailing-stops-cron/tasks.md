# Tasks: orchestration-trailing-stops-cron

## T1. Migration 0016: `trailing_stop_audit` table

- [ ] Create `apps/api/src/iguanatrader/migrations/versions/0016_trailing_stop_audit.py`.
- [ ] Revises `0015_trade_exit_columns`.
- [ ] Adds columns per proposal §New audit table.
- [ ] Two indexes: `(trade_id, swept_at DESC)` + `(tenant_id)`.
- [ ] `downgrade()` drops the table cleanly.
- [ ] Migration docstring explains purpose + NULL semantics + append-only invariant.

## T2. ORM model `TrailingStopAudit`

- [ ] Add `apps/api/src/iguanatrader/contexts/risk/orm.py::TrailingStopAudit` (sibling of existing risk ORM rows; check actual location — may need to live in a `models.py` if the project's risk context doesn't have an orm.py yet — match the convention used by `equity_snapshots`).
- [ ] `__tablename_is_append_only__ = True`, `__append_only_mutable_columns__ = frozenset()` (fully immutable).
- [ ] Mirror migration columns + types.
- [ ] `Base.metadata.create_all` test path picks it up automatically.

## T3. Repository: `TrailingStopAuditRepository`

- [ ] New file or extend existing risk repository: `add_audit_row(swept_at, trade_id, old_stop, new_stop, highest_close, atr, bars_evaluated) -> None`.
- [ ] `get_latest_for_trade(trade_id) -> TrailingStopAudit | None` (used by `_resolve_current_stop`).
- [ ] Tenant filter inherited from the slice-3 `tenant_listener`.

## T4. Helper: `_resolve_current_stop`

- [ ] In the sweep service module: `async def _resolve_current_stop(trade: Trade) -> Decimal`.
- [ ] Order: latest audit row's `new_stop` → else `Trade.proposal.stop_price` join.
- [ ] Raises `ValueError` if both are absent (defensive — proposal stop is NOT NULL at the DB level so this should never fire; raise rather than silently default).

## T5. Sweep service `TrailingStopSweepService.sweep`

- [ ] New file `apps/api/src/iguanatrader/contexts/risk/trailing_stop_sweep.py`.
- [ ] `TrailingStopSweepResult` frozen dataclass per proposal.
- [ ] `__init__(*, trading_repo, audit_repo, risk_caps_provider, market_data_port, clock=utc_now)`.
- [ ] `sweep()` per the proposal flow.
- [ ] Per-trade exceptions caught + counted in `trades_skipped_no_bars`; logged at WARNING with symbol + error type.
- [ ] Whole-sweep duration measured via `clock()` deltas.

## T6. Cron wiring in `OrchestrationService.bootstrap_routines`

- [ ] Add Optional `trailing_stop_sweep_service` param.
- [ ] When provided, register a 6th `JobSpec(name="trailing_stops_sweep", fn=_sweep_fn, cron_kwargs={"hour": "9-16", "minute": "*/15", "day_of_week": "mon-fri"})`.
- [ ] `_sweep_fn` awaits `trailing_stop_sweep_service.sweep()` and logs the result at INFO.
- [ ] Update the `routine_count` log to count the new job when present.

## T7. Unit tests for `_resolve_current_stop`

- [ ] 2 tests: one for the audit-row branch, one for the proposal-fallback branch.
- [ ] Pure helper tests; no I/O beyond an in-memory session.

## T8. Integration tests for the sweep

- [ ] `apps/api/tests/integration/test_trailing_stop_sweep.py` per the 10 scenarios listed in proposal §Tests.
- [ ] Reuse the fake `market_data_port` fixture used by other risk integration tests (`FakeMarketDataPort` or equivalent).
- [ ] Seeded trades + bars per scenario; assert audit row presence + counters.

## T9. Lint + typecheck

- [ ] `poetry run ruff check apps/api/src/iguanatrader/contexts/risk/trailing_stop_sweep.py apps/api/tests/integration/test_trailing_stop_sweep.py`.
- [ ] `poetry run black --check` same paths.
- [ ] `poetry run mypy --strict` same paths.
- [ ] **If Windows venv hangs >60s on any of the above**, skip local and trust Linux CI as gate per the documented fallback. State this explicitly in the PR body.

## T10. Commit + push + PR

- [ ] Conventional commit: `feat(orchestration-trailing-stops-cron): sweep job + audit table`.
- [ ] PR body MUST include §4.5 self-review block with the canonical 5-line shape (Profile/Reviewer/Self-review findings).
- [ ] STOP after `gh pr create`. Do not babysit CI. Report task complete with PR URL.
