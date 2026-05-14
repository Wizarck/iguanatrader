# Retrospective: portfolio-pnl-and-equity-series

- **PR**: [#143](https://github.com/Wizarck/iguanatrader/pull/143) (merged 2026-05-14, squash `0150631`).
- **Archive path**: `openspec/changes/archive/2026-05-14-portfolio-pnl-and-equity-series/`
- **Lines shipped**: 380 insertions / 2 deletions across 6 files. CI 14/14 green on first push.

## What worked

- **Backend money math, not frontend**: chose to compute `day_pnl_abs` / `day_pnl_pct` in Python (`Decimal`) instead of derive client-side from `equity.account_equity`. Three load-bearing reasons compounded: (a) JS `Number` on `Decimal`-as-string loses precision past ~15 digits — unacceptable for cents-level P&L on trading apps; (b) the same number must agree across web `/portfolio`, Telegram `/daily`, future postmarket email, and Slack alerts — one Python implementation, one source of truth; (c) future fields (dividends / FX / commissions) extend the formula in Python without N parallel UI rewrites. The proposal documented this trade-off explicitly so the next dashboard slice ([[portfolio-dashboard-mvp]]) consumes it as a pure renderer.
- **Selective DTO enrichment** — only added the 2 fields the frontend cannot safely derive (`day_pnl_abs`, `day_pnl_pct`). Did NOT add `total_value`, `cash_balance`, `position_count` since those are 1:1 mirrors of existing fields (`equity.account_equity`, `equity.cash_balance`, `len(open_trades)`) — no money math, no precision risk, no DTO bloat. Discipline that pays off when the DTO inevitably grows in v2.
- **`Query(ge=1, le=365)` on the timeseries endpoint** — Pydantic does the validation, returns 422 on out-of-range. Matches the existing slice-4 error contract (not 400). One test case pins the contract for both directions.
- **Re-used the existing `EquitySnapshotListOut` DTO** planted by T1 — no DTO churn for the new endpoint. The slice-5 OpenAPI typegen picked it up automatically + regenerated `packages/shared-types/src/index.ts` in CI without manual intervention.
- **Worktree-isolation Step 0 prevention** WORKED. The previous bug ([[agent-worktree-isolation-windows]]) didn't recur this run — `pwd`-pinning + path-prefix discipline forced the agent to write into its worktree throughout. Validated empirically: parent-side `git status` showed zero rogue files in main.

## What didn't

- **Local linters hung on Windows venv (again)** — `poetry run ruff check apps/api/src apps/api/tests` and `poetry run black --check apps/api/` both hung past 3 minutes when invoked across the whole tree. Scoping to just the 4 touched files (`poetry run ruff check <file1> <file2> ...`) returned in <2s. Same env quirk that bit β (PR #142) at the `black --check` step. Pre-flag: on this Windows dev box, always scope ruff/black/mypy invocations to specific touched files instead of letting them walk the whole tree — saves 10× wall-time. The agent's prompt instructed `poetry run black --check apps/api/` (tree-wide), which contributed to the agent timing out at the 16-min mark waiting for that single command.
- **Agent timed out at ~16min, never committed or pushed** — the slice's code was complete + correct in the worktree, but the agent's final phase (waiting for `black --check apps/api/` to return) hung past its task budget. Parent agent took over: spot-check, branch switch (branch already existed because agent had created it before running black), commit, push, PR. ~5 extra minutes of parent time. Pre-flag: when spawning agents for slice work, the Step 5 "local CI before push" block should scope linters to touched files only, not tree-wide — explicitly write `poetry run black --check <file1> <file2>` in the prompt instead of `poetry run black --check apps/api/`.
- **Branch-already-existed friction** — `git switch -c feat/<slug>` failed because the agent had already created the branch (before its hang). `git switch feat/<slug>` (without `-c`) was the right command. Pre-flag: when taking over a timed-out agent's work, check `git branch -av | grep <slug>` before assuming the branch needs creation.

## Carry-forward

- **Multi-timezone day boundary** — v1 uses UTC midnight. SaaS tenants in EU/Asia want their own day = v1.5 follow-up (`portfolio-day-boundary-tenant-tz`). Surface area: tenant table needs `timezone: str` column + the route reads `today_midnight(tenant.timezone)` instead of UTC.
- **"Yesterday's close" baseline** — v1 uses first-snapshot-today. If the daemon was down overnight the baseline shifts to whenever it first ticked today. True "yesterday close" requires `MAX(created_at) WHERE created_at < today_utc_midnight` + a null branch for first-ever-day. Defer until an operator notices an off-baseline day_pnl number.
- **Equity series cursor pagination** — `EquitySnapshotListOut.next_cursor` stays null in v1; max 365 days × snapshot-frequency fits in one response. Revisit when snapshot frequency goes sub-minute or the SaaS UI wants more.
- **Sparkline rendering** — frontend consumer is [[portfolio-dashboard-mvp]] (re-scoped against this slice's enriched DTO). Pure-SVG line chart, no chart-lib dependency per the original proposal.
- **`PortfolioSummaryOut` extension envelope** — when day P&L grows to include commission-adjusted P&L or per-instrument breakdown, the room is in `PortfolioSummaryOut`. Don't fork into a separate DTO unless the response shape diverges from "snapshot + lists + scalar totals".

## Pattern usage

- **Money-math-in-Python, frontend-as-pure-renderer** — load-bearing decision the next dashboard slice depends on. Pattern: any Decimal computation lives backend. Frontend reads `model_validate`-stable numbers as strings + renders. Currency formatting + colour-by-sign + percent multiplication (×100) are presentation concerns, NOT calculation.
- **`Decimal | None` for "not-yet-available" baselines** — null signals "the system can't compute this yet (no baseline snapshot)" cleanly. Frontend switches on null → "—". Avoids the antipattern of returning `0` or `-1` as sentinels.
- **`Query(ge=N, le=M)`-driven endpoint sanity** — Pydantic boundary validation at the FastAPI signature line, not in the body. 422 on out-of-range. One annotation, full contract. Pattern reusable for any range-bounded query param (window, limit, lookback).
- **`today_utc_midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)`** — explicit + testable + timezone-stable. Don't reach for SQLite's `CURRENT_DATE` (timezone-ambiguous; behaves differently on Postgres).
- **Scope linters to touched files when iterating locally on Windows** — `ruff check <files>` and `black --check <files>` complete in <2s scoped vs hanging when tree-wide. CI on Linux is the source-of-truth for tree-wide passes.
- **Step 0 worktree-path-pinning anti-bug template** — proven effective this run. Future agent prompts shipping slice work MUST include the `pwd` + "absolute paths under worktree-root only" preamble.
