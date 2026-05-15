# Retrospective: trades-add-exit-and-realised-pnl-columns

- **PR**: [#165](https://github.com/Wizarck/iguanatrader/pull/165) (merged 2026-05-15, squash `8abf85b`).
- **Archive path**: `openspec/changes/archive/2026-05-15-trades-add-exit-and-realised-pnl-columns/`
- **Lines shipped**: 377 insertions across 4 files (migration + ORM + 2 test files).

## What worked

- **Schema-only slice with NULL-as-unknown semantics** — clean separation between schema (this slice) and write-side wiring (next slice). Legacy rows stay NULL; risk aggregations treat NULL as "no contribution".
- **Whitelist + schema in same PR** — `__append_only_mutable_columns__` extended for `exit_reason` + `realised_pnl` so the future close-flow UPDATE doesn't get rejected. Without this, the slice would be broken by design.
- **Model-level CheckConstraint mirrors migration** — `__table_args__` declares the same constraint as the DB migration, so the in-memory SQLite test path (`Base.metadata.create_all`) ships the constraint too.

## What didn't

- **Agent budget exhausted mid-slice (3rd recurrence)** — agent completed implementation + tests but stopped before commit/push. Parent (me) inherited the worktree state, did black manual fix (Windows venv couldn't run lints), pushed. Pattern: 3 agents in a row (auth-aging, trades-exit-cols) have hit this. Pre-flag: when an agent enters the "lint + commit + push" final phase, consider giving it an explicit budget hint (e.g. "tasks 1-9 done; 10-13 remain; ensure you finish") OR build a checkpoint marker so the parent can resume.
- **Windows venv hangs on lints** — `poetry run ruff/black/mypy` hung past 5 min on this worktree. Same issue surfaced repeatedly across recent sessions. CI on Linux is the source of truth. Carry-forward: `chore-investigate-windows-venv-lint-hang` slice.
- **Black wanted single-line CHECK constraint** — my initial commit had implicit string concat across two lines. Black collapses adjacent string literals onto one line if they fit in 100 chars. Easy fix; one-line follow-up commit.

## Carry-forward

- **`wire-risk-state-real-data`** — next slice. Now unblocked. The state builder reads from these columns to populate `RiskState.recent_stoploss_count_trailing` + P&L aggregates.
- **`trades-close-flow-exit-classification`** — the close-flow service that populates the columns at trade-close time. Separate slice; without it, columns stay NULL forever.
- **Windows venv lint hang investigation** — affects every slice's local-pre-CI confidence. Worth a one-off diagnostic.
- **Skip-local-lints fallback** — when Windows venv hangs, parent agent can skip local lints and trust CI as gate. Recovery cost: one push per black/ruff/mypy issue. Acceptable trade-off when local is broken.

## Pattern usage

- **NULL-as-unknown for additive columns** — when adding columns mid-lifecycle, NULL semantics let the slice ship without a forced backfill. Risk aggregations skip NULL via SQL semantics (`SUM` ignores; `WHERE col = 'x'` excludes NULL). Promote to playbook §additive-schema-migration-pattern.
- **Whitelist + schema in same PR** — when adding columns to an append-only-listened table, the whitelist extension MUST ship with the column. Splitting causes a half-broken state.
- **Skip-local-lints when env broken** — trust CI as the final gate when local is unreliable. Pay the cost of one fix-push round-trip per issue. Acceptable when the alternative is hours of debugging Windows venv.
