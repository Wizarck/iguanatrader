# Proposal: trades-list-and-detail

> **Wire the `/trades` dashboard tab to consume the existing `trades-read-endpoints` backend** — `GET /api/v1/trades` + `/trades/{id}` + `/trades/{id}/fills` already ship JSON; today the UI is a static `PlaceholderCard`. Picked over `/portfolio` because the trades backend is real (verified) while portfolio is still 501 stubs (parallel slice `trading-routes-portfolio-strategies-bodies` lands those bodies).

## Why

The 20-slice catalogue (`docs/openspec-slice.md`) entry for slice `trades-read-endpoints` (PR #112, 2026-05-08) shipped 3 read endpoints:

- `GET /api/v1/trades` → `TradeListOut { items: TradeOut[], total, next_cursor }`
- `GET /api/v1/trades/{trade_id}` → `TradeOut`
- `GET /api/v1/trades/{trade_id}/fills` → `FillListOut { items: FillOut[], total, next_cursor }`

These are real and tenant-scoped (verified via `apps/api/src/iguanatrader/api/routes/trades.py:42-95`). The UI hasn't caught up — `/trades` shows `PlaceholderCard` since PR #136.

This slice closes the UI gap end-to-end:

- Browser hits `/trades` → SvelteKit `+page.server.ts` calls `${API_BASE_URL}/api/v1/trades` with cookie forwarding → renders a sortable trades table.
- Browser hits `/trades/{id}` → server load fetches `/trades/{id}` + `/trades/{id}/fills` in parallel → renders trade summary card + chronological fills table.
- Empty state when no trades → honest copy ("No trades aún. Arranca el daemon: `iguanatrader trading run --mode paper`").
- Error state when API 5xx → `loadError` alert.

Sub-pattern (server-load proxy + table + empty/error state) is reused by `strategies-config-ui`, `risk-dashboard-ui`, etc. — the next 5 dashboard slices follow the same shape.

## What

### Page-level server loads

**`apps/web/src/routes/(app)/trades/+page.server.ts`** (NEW). Calls `GET /api/v1/trades` via the existing `${API_BASE_URL}/...` + cookie-forwarding pattern (same shape as `(app)/settings/+page.server.ts` post-PR #130). Returns `{ trades: TradeOut[], total: number, loadError?: string }`.

**`apps/web/src/routes/(app)/trades/[id]/+page.server.ts`** (NEW). Fetches `/trades/{id}` + `/trades/{id}/fills` in parallel. Returns `{ trade: TradeOut, fills: FillOut[], loadError?: string }`. Surfaces `loadError` when either call fails 4xx/5xx or network throws (no 404 special-casing — page renders the alert with retry hint).

### Page UI

**`apps/web/src/routes/(app)/trades/+page.svelte`** — replace `PlaceholderCard` body with:

- **Trades table** (full-width): columns `Symbol`, `Side`, `Qty`, `Mode`, `State`, `Opened`, `Closed`. Sorted server-side by `created_at DESC` (already done by the repo). Row hover highlight. Each row is a link to `/trades/{id}` (full-row clickable area, no nested `<a>` issues — use SvelteKit `goto` on row click + `aria-rowindex`/`role="link"`).
- **Side / state badges**: small pill components with OKLCH colour by value (`buy` → `--success` tint, `sell` → `--destructive` tint; `open` → `--accent` tint, `closed` → `--mute` tint).
- **Empty state**: when `trades.length === 0` → render `EmptyState` card: "No trades aún. Arranca el daemon: `iguanatrader trading run --mode paper`." with hint linking to docs/mvp-deploy.md.
- **Error state**: `loadError` set → `<div class="error" role="alert">` with retry hint.

**`apps/web/src/routes/(app)/trades/[id]/+page.svelte`** (NEW) — trade detail:

- **Trade summary card** (top): symbol + side badge + state badge + qty + mode + opened/closed timestamps (ISO 8601, per [[feedback_date_format_preference]]).
- **Fills table** (bottom): columns `Filled at`, `Qty`, `Price`, `Commission`, `Broker fill ID`. Empty list → "Sin fills aún." inline message (NOT an `EmptyState` card — the trade exists, the fills list is just empty).
- **Back link** to `/trades`.

### Reusable components (NEW)

- **`apps/web/src/lib/components/EmptyState.svelte`** — `{ title, body, hint? }`. OKLCH styling matching `PlaceholderCard` but semantically distinct (no "future slice" copy; this is genuinely empty data, not pending UI). Will be reused by 5+ subsequent dashboard slices.
- **`apps/web/src/lib/components/Badge.svelte`** — `{ label, variant: 'success' | 'destructive' | 'accent' | 'mute' }`. Small pill, OKLCH-tinted background + foreground.
- **`apps/web/src/lib/components/DataTable.svelte`** — generic typed table with column-config slot pattern (`<DataTable rows={trades} columns={[...]} on:rowclick={...} />`). Hoist now so `/strategies` + `/risk` reuse it without re-extraction churn.

### Tests

- **`apps/web/tests/trades-list-page.test.ts`** (vitest):
  1. Happy path — mocked `/trades` → assert table rows rendered + row click navigates to `/trades/{id}`.
  2. Empty list → `EmptyState` rendered + daemon-start hint shown.
  3. API 503 → `loadError` set + alert rendered + page does not crash.
  4. Side badges: `buy` row has `--success` class, `sell` has `--destructive` class.

- **`apps/web/tests/trades-detail-page.test.ts`** (vitest):
  1. Happy path — mocked `/trades/{id}` + `/trades/{id}/fills` → summary card + fills table.
  2. No fills → "Sin fills aún." inline copy shown, no `EmptyState`.
  3. API 503 on either endpoint → `loadError` rendered.
  4. Back link → navigates to `/trades`.

- **`apps/api/tests/integration/test_trades_route_smoke.py`** (NEW) — fresh empty tenant returns `{items: [], total: 0, next_cursor: null}`. Defense-in-depth.

### Storybook

3 stories each for `EmptyState.stories.ts`, `Badge.stories.ts`, `DataTable.stories.ts` — variants per intended use cases.

## Out of scope

- **Pagination cursor** — backend returns `next_cursor: null` in v1; UI doesn't render a paginator yet. Add when v2 cursor lands.
- **Sortable column headers** — server already sorts by `created_at DESC`; client-side sort dropdown defers to follow-up.
- **Trade cancellation / state mutation** — read-only in this slice; mutation lives in `trades-mutation-ui` (separate slice).
- **Realtime updates via SSE** — page is `load`-fn driven; refresh requires nav. SSE wiring is `trades-sse-realtime` (separate slice).
- **Per-tenant currency formatting** — defaults to USD for commission display. Currency dropdown is v1.5.
- **Wiring `/portfolio`, `/strategies`** — `/portfolio` blocked on `trading-routes-portfolio-strategies-bodies` (in-flight parallel slice); `/strategies` follows the same backend slice.
