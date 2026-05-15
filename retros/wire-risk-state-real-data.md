# Retrospective: wire-risk-state-real-data

- **PR**: [#166](https://github.com/Wizarck/iguanatrader/pull/166) (merged 2026-05-15, squash `6ed128e`).
- **Archive path**: `openspec/changes/archive/2026-05-15-wire-risk-state-real-data/`
- **Lines shipped**: 766 insertions across 2 files (repository.py +218, integration test +561).

## What worked

- **Placeholder → real loader replacement in a single file** — `RiskRepository.load_risk_state` was the only seam to flip. 8 risk protections + kill-switch auto-activate flipped from inert-on-default-state to live-against-real-data with zero engine edits.
- **6 small helpers, each one query** — `_open_trade_count`, `_latest_equity`, `_peak_equity_since`, `_drawdown_pct`, `_realised_pnl_since`, `_stoploss_streak_count`, `_seconds_since_last_close_by_symbol`. Each helper takes (session, tenant, window) and returns a primitive; the public method composes them into `RiskState`. Trivially testable in isolation.
- **NULL-as-zero contract honored in SQL** — `realised_pnl IS NOT NULL` + `SUM(coalesce(realised_pnl, 0))` excludes legacy rows rather than coercing to 0. Stoploss-guard tally counts only `exit_reason = 'stop'`, so NULL contributes zero. This was the prerequisite contract from PR #165's slice and it survived the join intact.
- **`_FALLBACK_CAPITAL = Decimal("10000")`** matches `DEFAULT_EQUITY` in the strategy modules. When the equity-snapshot daemon hasn't shipped yet, the engine sees a stable baseline (drawdown stays 0) rather than divide-by-zero.
- **Tenant-scoping inherited from listener** — relied on the slice-3 `tenant_listener` rather than hand-wired `WHERE tenant_id = ?` in each query. One explicit `test_state_is_tenant_scoped` validates cross-tenant isolation. Less code, less drift risk.
- **Naive-datetime defensive coerce in `_seconds_since_last_close_by_symbol`** — SQLite TEXT round-trips can produce tzinfo-naive `datetime`; the helper coerces to UTC before subtraction. Production rows insert tz-aware via ORM, but the guard is cheap defence against SQLite test paths.

## What didn't

- **Agent budget exhaustion (4th recurrence)** — agent finished implementation but stopped before commit/push. Parent inherited worktree state, hit lint failures, pushed fix commit `9a62aaa`. Pattern continues: every slice with non-trivial test surface hits the budget ceiling. Encoded anti-budget directives into the agent prompt this round (explicit "tasks N-M remain; ensure you finish"); didn't help. **Carry-forward**: write an explicit `worker-budget-checkpoint` slice in the playbook — formalize the parent-resumes-on-budget pattern as a first-class workflow, not an exception path.
- **Lint failures on push** — `stmt = (select(...).where(...))` had redundant parens; isort wanted ORM imports before models/repository. Both are stylistic, both would have been caught by `ruff` + `isort` locally. Windows venv hang prevented local check; CI caught them (60s feedback). Acceptable cost.
- **Windows venv lint hang (recurring)** — `poetry run python --version` produced no output after 30s on the worktree path. Skipped local lints; trusted CI as gate. Documented in PR body. This is the 4th slice in a row this has happened. **Carry-forward `chore-investigate-windows-venv-lint-hang` is now overdue.**

## Carry-forward

- **`orchestration-trailing-stops-cron`** — next slice in queue. PR #163 shipped `compute_trailing_stop` as a pure function; needs a daemon/cron caller that invokes it on each open trade with current market price + persists the new stop. With `load_risk_state` now live, the cron can also gate updates by risk state if needed.
- **`trades-close-flow-exit-classification`** — without this, `exit_reason` + `realised_pnl` stay NULL forever, which means stoploss-guard / day-loss / week-loss / drawdown all return zero in production. The state loader is correct; it just sees a database with no closed trades classified. Critical unblocker for v1.5 protections firing on real positions.
- **Equity-snapshot daemon** — drawdown stays at 0 until this ships (only one snapshot row → peak == latest → drawdown 0). Documented as out-of-scope degradation in PR body. Separate slice.
- **`chore-register-sqlite-datetime-adapter`** — Python 3.13 sqlite3 deprecation triggers `filterwarnings=["error"]` escalation. Adding a `register_adapter(datetime, isoformat)` shim once would let us drop the defensive str/datetime coerces in `_seconds_since_last_close_by_symbol` and `_classify_password_aging`.
- **`chore-investigate-windows-venv-lint-hang`** — 4-slice streak of CI-as-only-gate. Worth one diagnostic session.
- **`worker-budget-checkpoint`** (new) — formalize parent-resume-on-budget-exhaust as a playbook workflow, not a recurring "what didn't" entry.

## Memory updates

- `project_risk_state_placeholder.md` is now **stale** — the placeholder is gone, the loader is real. Update or retire that memory entry.
- New invariant worth remembering: **drawdown stays 0 until equity-snapshot daemon ships** — load_risk_state composes peak/latest from `equity_snapshots`, and with only one row (or zero rows → fallback constant), `(peak - latest) / peak == 0`. Document this so future debugging of "drawdown protection never fires" doesn't trigger a witch-hunt against the loader.

## Pattern usage

- **Placeholder-to-real loader pattern** — when a multi-protection engine consumes a `State` struct, build the struct in *one* repository method behind a stable interface. Engine, protections, and tests can all be merged ahead of time against a default-zero/no-update state (inert-by-construction); flipping to real data is a single-PR, single-file change. Promote to playbook §inert-state-then-flip-loader.
- **Helper-per-field decomposition** — public `load_risk_state` orchestrates; one private helper per `RiskState` field. Each helper is one SELECT, easy to test, easy to read. Avoids monolithic 200-line method.
- **SQL-level NULL semantics over Python coalesce** — `coalesce(SUM(col), 0)` + `WHERE col IS NOT NULL` at the SQL boundary is cleaner than `state.pnl = sum_or_zero(pnl) if pnl is not None else 0` in Python. Lets the DB handle the empty-set case once; the helper returns a primitive ready to drop into the Pydantic model.
