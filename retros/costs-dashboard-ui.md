# Retrospective: costs-dashboard-ui

- **PR**: [#147](https://github.com/Wizarck/iguanatrader/pull/147) (merged 2026-05-14, squash `b6aaff2`).
- **Archive path**: `openspec/changes/archive/2026-05-14-costs-dashboard-ui/`
- **Lines shipped**: 925 insertions / 10 deletions. CI 15/15 green on first push.

## What worked

- **Agent shipped end-to-end without parent intervention** — second agent this session (after PR #145) that completed the full cycle solo (code + commit + push + PR + CI green). The combination of Step 0 worktree-pinning + scoped linters + explicit reference-pattern citation in the prompt is the working recipe.
- **3 parallel fetches via `Promise.all`** — mirror of portfolio pattern; per-endpoint Spanish error messages so the user can tell which call failed.
- **`Intl.DateTimeFormat('es-ES', {month: 'long', year: 'numeric', timeZone: 'UTC'})`** for the "Mayo 2026" period header — first slice to use locale-specific formatting. UTC pinned to match the backend's UTC-midnight day boundary from [[portfolio-pnl-and-equity-series]].
- **`costPerTradeColour(value)` tier mapper** — null → destructive (unknown = warning by design), <1 → success, 1-5 → accent, >5 → destructive. Operator-meaningful tiers, not arbitrary.
- **Null `cost_per_trade_usd` renders "—" + subtitle "Sin trades cerrados aún"** — honest. Distinguishes "no data" from "zero cost".
- **Cache stats as subtitle** — "<total_calls> calls (<cached_calls> cached)" surfaces the cache-hit signal without dedicated UI. Cache hit ratio chart deferred to v1.5.
- **`it.each` for the 3 endpoint-failure cases** — DRY test code; same pattern reusable for any multi-fetch page.

## What didn't

- **Nothing notable** — slice was specced cleanly + agent executed cleanly. The agent's report flagged a `request_id` field that wasn't in the proposal but that's an internal type addition, no behaviour change.

## Carry-forward

- **Budget gauges + alerts** — `BudgetStateDTO` exists in DTOs; surfacing it requires a budget-config UI first (`costs-budget-config-ui`).
- **SSE realtime** (`CostSnapshotEvent`) — separate slice once SSE infra extends.
- **Historical USD timeseries** — chart of spend over time. v1.5.
- **Per-model breakdown** — `PerModelBreakdown` exists in DTOs; surface in v1.5 (`costs-per-model-ui`).
- **Cache hit ratio chart** — derivable from `cached_calls / total_calls`; v1.5.

## Pattern usage

- **`Intl.DateTimeFormat('es-ES', ...)` with `timeZone: 'UTC'`** — locale-specific human-readable dates; UTC pinned to match backend day boundary. Pattern reusable for any period-aware dashboard tab.
- **Tier-colour mapper per domain** — `$lib/<domain>/format.ts` (costs) or `$lib/<domain>/colour.ts` (risk). Same shape; per-domain semantics.
- **`it.each` for parametrised CI-failure tests** — covers each endpoint's 503 path without duplication. Reusable for any multi-fetch slice.
- **Null + high-tier both map to `destructive`** — when "unknown" is operationally indistinguishable from "bad", collapse them visually. Forces operator to investigate either way.
