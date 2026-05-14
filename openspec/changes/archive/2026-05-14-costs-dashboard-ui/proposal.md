# Proposal: costs-dashboard-ui

> **Wire the `/costs` dashboard tab to consume the 3 cost endpoints** — `/costs/summary` + `/costs/by-provider` + `/costs/per-trade`. Read-only LLM-cost observability for the current month.

## Why

Backend shipped in slice O1 (`observability-cost-meter`). 3 GET endpoints return USD spend rollups. Today UI is `PlaceholderCard`. This slice replaces it with a single read-only tab.

Pattern: 3 parallel fetches (same as portfolio), reuse `EmptyState`/`Badge`/`DataTable`, OKLCH tokens, format helpers from `$lib/portfolio/format.ts`.

## What

### Server load

**`apps/web/src/routes/(app)/costs/+page.server.ts`** (NEW). 3 parallel fetches:
- `GET ${API_BASE_URL}/api/v1/costs/summary` → `CostSummaryDTO`
- `GET ${API_BASE_URL}/api/v1/costs/by-provider` → `CostByProviderDTO`
- `GET ${API_BASE_URL}/api/v1/costs/per-trade` → `CostPerTradeDTO`

Returns `{ summary, byProvider, perTrade, loadError }`.

### Page UI

**`apps/web/src/routes/(app)/costs/+page.svelte`** — replace `PlaceholderCard`:

- **Header**: `<h1>Costs</h1>` + period range "MMM YYYY" computed from `summary.period_start` ISO 8601 (e.g., "Mayo 2026").
- **Summary card** (NEW component `CostsSummaryCard`): 3-cell grid:
  - Total USD this period: `formatMoney(summary.total_cost_usd, "USD")`.
  - Total calls: integer + small "(<cached_calls> cached)" subtext.
  - Cost per trade: `summary.total_cost_usd / perTrade.closed_trades_count` formatted; if `perTrade.cost_per_trade_usd === null` → "—" with subtitle "Sin trades cerrados aún".
- **By-provider table** (reuses `DataTable`): columns `Provider`, `USD spent`, `Call count`. Sorted server-side. Row colour normal; values via `formatMoney` + plain integer.
- **Per-trade card** (NEW component `CostPerTradeCard`): big number = `cost_per_trade_usd` (or "—"), small "= <total_llm_cost_usd> / <closed_trades_count>" beneath. Coloured tone:
  - `--success` if cost_per_trade_usd < 1.0 USD
  - `--accent` if 1.0–5.0 USD
  - `--destructive` if >5.0 USD or null (high-cost-or-unknown warning)
- **Empty state**: when `summary.total_calls === 0` → `EmptyState` "Sin coste registrado aún. Los costes se acumulan cuando los nodes LangGraph y APIs externas se invocan."
- **Error state**: `loadError` → red alert.

### New components

- **`apps/web/src/lib/components/CostsSummaryCard.svelte`** — `{ summary: CostSummaryDTO, perTrade: CostPerTradeDTO }`. 3-cell grid card.
- **`apps/web/src/lib/components/CostPerTradeCard.svelte`** — `{ perTrade: CostPerTradeDTO }`. Big-number card with tier colour.

### TS types

`apps/web/src/lib/costs/types.ts` — mirrors of `CostSummaryDTO`, `CostByProviderDTO`, `CostPerTradeDTO`, `PerProviderBreakdown`.

### Tests

- **`apps/web/tests/costs-page.test.ts`** (vitest):
  1. Happy path — summary + by-provider table + per-trade card render.
  2. Empty (`total_calls === 0`) → `EmptyState`.
  3. API 503 on any of 3 → `loadError` alert.
  4. `cost_per_trade_usd === null` → "—" + warning subtitle.
  5. High cost-per-trade (>5 USD) → `destructive` class on the card.

- **`apps/web/tests/costs-format.test.ts`** (vitest, pure): tier-colour mapper `costPerTradeColour(value: number | null): 'success' | 'accent' | 'destructive'`.

### Storybook

3 variants each for `CostsSummaryCard.stories.ts` + `CostPerTradeCard.stories.ts` (idle / typical / over-budget).

## Out of scope

- **Budget gauges + alerts** — `BudgetStateDTO` exists in DTOs; surfacing it requires a budget-config UI first (`costs-budget-config-ui`).
- **SSE realtime** (`CostSnapshotEvent`) — separate slice.
- **Historical timeseries** (USD spend over time chart) — v1.5.
- **Per-model breakdown** — `PerModelBreakdown` exists; surface in v1.5 (`costs-per-model-ui`).
- **Cache hit ratio chart** — derivable from `cached_calls / total_calls`; defer to v1.5.
