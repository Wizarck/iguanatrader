# Proposal: portfolio-dashboard-mvp

> **Wire the `/portfolio` dashboard tab to consume the now-real backend** — `GET /api/v1/portfolio` (PR #142) returns `PortfolioSummaryOut` enriched with `day_pnl_abs`/`day_pnl_pct` (PR #143); `/portfolio/positions` (PR #142) returns `PositionListOut`; `/portfolio/equity/series?days=30` (PR #143) returns `EquitySnapshotListOut` for the sparkline. Today the UI is a `PlaceholderCard`. This slice replaces it. **First proper dashboard slice that ships the full overview pattern** (summary card + sparkline + table).

## Why

The original draft of this proposal (2026-05-13, blocked-and-rescoped) assumed a `PortfolioSummaryOut` with top-level `total_value` / `cash_balance` / `day_pnl` fields. Reality (post-PR #142): the DTO is `{ equity, open_trades, open_orders, day_pnl_abs, day_pnl_pct }`. This re-scoped slice consumes the real shape.

Pattern carry-over from [[trades-list-and-detail]] (PR #141): `+page.server.ts` does parallel `fetch` against `${API_BASE_URL}` with cookie forwarding; the page renders summary + content OR `EmptyState` OR `loadError` alert. `EmptyState`, `Badge`, `DataTable` are already shipped in `$lib/components/` — reuse, don't re-extract.

This unblocks the next 4 dashboard slices (`strategies-config-ui`, `risk-dashboard-ui`, `costs-dashboard-ui`, `approvals-dashboard-ui`) which follow the same shape.

## What

### Page-level server load

**`apps/web/src/routes/(app)/portfolio/+page.server.ts`** (NEW). Three parallel fetches:

- `GET ${API_BASE_URL}/api/v1/portfolio` → `PortfolioSummaryOut`
- `GET ${API_BASE_URL}/api/v1/portfolio/positions` → `PositionListOut`
- `GET ${API_BASE_URL}/api/v1/portfolio/equity/series?days=30` → `EquitySnapshotListOut`

All three use `Promise.all` + cookie forwarding (same pattern as `(app)/trades/+page.server.ts`). Any 5xx or network throw → returns `loadError: string` so the page renders the alert without crashing.

Returns shape:
```ts
{
  summary: PortfolioSummaryOut | null,
  positions: PositionOut[],
  equity_series: EquitySnapshotOut[],
  loadError: string | null,
}
```

### Page UI

**`apps/web/src/routes/(app)/portfolio/+page.svelte`** — replace the `PlaceholderCard` body with:

- **Summary card** (top, full width): `PortfolioSummary` component — total value (= `summary.equity.account_equity`) + day P&L (uses `summary.day_pnl_abs` + `summary.day_pnl_pct`; coloured `--success` ≥0, `--destructive` <0; "—" when null) + cash (= `summary.equity.cash_balance`) + position count (= `positions.length`).
- **Equity sparkline** (right of summary, ~240×72px): `EquitySparkline` component — pure SVG line chart over `equity_series.map(s => s.account_equity)`. Hover tooltip showing date + equity. No external chart lib. When `equity_series.length === 0` → render "Sin datos aún" inline (NOT an `EmptyState` card).
- **Positions table** (bottom, full width): existing `DataTable` (shipped in α/PR #141) with columns `Symbol`, `Side`, `Qty`, `Avg entry`, `Last`, `Unrealized P&L`, `Opened`. Sort server-side (positions endpoint already returns `opened_at DESC`). Side cell uses `Badge` `success`/`destructive`. `Avg entry` / `Last` / `Unrealized P&L` cells render `—` when null (v1: `last_price` + `unrealized_pnl` are always null per `market-data-snapshot-port` not-yet-shipped — see [[trading-routes-portfolio-strategies-bodies]] retro).
- **Empty state**: when `summary.equity.snapshot_kind === "empty"` AND `positions.length === 0` AND `equity_series.length === 0` → render single `EmptyState` card: "No portfolio activity aún. Arranca el daemon: `iguanatrader trading run --mode paper`." with hint linking to `docs/mvp-deploy.md`.
- **Error state**: `loadError` set → `<div class="error" role="alert">` with retry hint.

### New reusable components

**`apps/web/src/lib/components/PortfolioSummary.svelte`** (NEW) — props `{ totalValue, dayPnlAbs, dayPnlPct, cash, positionCount, currency }`. All `Decimal`-as-string. Renders a 4-cell grid card with OKLCH styling. `dayPnlAbs`/`dayPnlPct` may be null (renders "—"); when present, sign-coloured via the existing `--success` / `--destructive` tokens. Format helpers:

- `formatMoney(value: string, currency: string)` → `"$237.45"`. Uses `Intl.NumberFormat` for *display only*, never for arithmetic (the value is already a Decimal-as-string from backend).
- `formatPercent(value: string)` → `"+0.24%"` (multiplies ×100, 2 decimals, signed). Display only.

Helpers live in `$lib/portfolio/format.ts` so they are unit-testable without a DOM.

**`apps/web/src/lib/components/EquitySparkline.svelte`** (NEW) — props `{ snapshots: EquitySnapshotOut[], width = 240, height = 72 }`. Renders a single `<svg>` `<path>` computed from `snapshots[].account_equity` (parsed via `Number(s.account_equity)` for plotting only — values are bounded, ~$0–$1M typical, JS Number suffices for *plotting precision*; NEVER for money math). Hover dot + tooltip via `<title>` element. No external lib. Path generator lives in `$lib/portfolio/sparkline.ts` as a pure function: `buildSparklinePath(values: number[], width: number, height: number): string` — unit-testable.

### Frontend types

`apps/web/src/lib/portfolio/types.ts` — mirror of `EquitySnapshotOut` + `PositionOut` + `PortfolioSummaryOut` + their list-wrappers (same pattern as `$lib/trades/types.ts` from α). Thin re-export once the OpenAPI typegen runs.

### Tests

- **`apps/web/tests/portfolio-page.test.ts`** (vitest):
  1. Happy path — mocked all 3 endpoints → assert summary card + sparkline path + positions table rendered.
  2. Empty data — `summary.equity.snapshot_kind="empty"` + `positions=[]` + `equity_series=[]` → `EmptyState` rendered with daemon-start hint.
  3. API 503 on any of the 3 → `loadError` set + alert rendered + page does not crash.
  4. Negative day P&L → cell has `--destructive` colour class.
  5. Null day P&L (`day_pnl_abs: null`) → cell renders "—" (NOT colour-coded).
  6. Positions table — `last_price: null` row renders "—" not "null".

- **`apps/web/tests/sparkline.test.ts`** (vitest, pure): `buildSparklinePath` returns valid SVG `d` attribute for 0/1/2/N points; clamps Y to [0, height]; clamps X to [0, width].

- **`apps/web/tests/portfolio-format.test.ts`** (vitest, pure): `formatMoney("237.45", "USD")` → `"$237.45"`; `formatPercent("0.0024")` → `"+0.24%"`; signed/unsigned/null/zero cases.

### Storybook

3 stories each in `apps/web/src/lib/components/PortfolioSummary.stories.ts` + `EquitySparkline.stories.ts` — variants: loaded / empty / negative.

## Out of scope

- **Position drill-down to `/portfolio/{trade_id}`** — separate slice (`portfolio-position-detail`).
- **Realtime updates via SSE** — page is `load`-fn driven; refresh requires nav. SSE wiring is `portfolio-sse-realtime`.
- **Per-tenant currency formatting** — defaults to USD. Currency dropdown is v1.5.
- **Chart-lib choice** (Plotly / Chart.js) — bare SVG sufficient for MVP sparkline. Choose a lib only if a future slice needs candlestick / multi-series / zoom.
- **`market-data-snapshot-port`** — `last_price` / `unrealized_pnl` stay null in v1. The positions table renders "—". When that slice lands, the table will show live values without a UI change (frontend already handles null).
- **Sparkline X-axis tick labels** — hover tooltip shows dates; explicit axis labels defer to follow-up.
- **Multi-timezone day boundary** — backend uses UTC midnight (per [[portfolio-pnl-and-equity-series]] retro). UI inherits.
