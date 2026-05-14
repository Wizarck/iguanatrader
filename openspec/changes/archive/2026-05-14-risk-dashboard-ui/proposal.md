# Proposal: risk-dashboard-ui

> **Wire the `/risk` dashboard tab to consume `GET /api/v1/risk/state`** — caps + state + utilisation + kill-switch flag. Read-only v1; the `POST /override` action belongs to a future slice (`risk-override-ui`).

## Why

Backend shipped in slice K1 (`risk-engine-protections`). `GET /risk/state` returns `RiskStateResponse { caps, state, utilisation, kill_switch_active, fetched_at }`. Today the UI is a `PlaceholderCard`. This slice replaces it with a single dashboard tab showing the operator's risk posture at-a-glance.

Pattern continues from portfolio + strategies: server-load + cookie forwarding, reuse `EmptyState`/`Badge`/`DataTable`, honest "—" for null, OKLCH tokens.

## What

### Server load

**`apps/web/src/routes/(app)/risk/+page.server.ts`** (NEW). Single fetch:
- `GET ${API_BASE_URL}/api/v1/risk/state` → `RiskStateResponse`.

Returns `{ risk: RiskStateResponse | null, loadError: string | null }`.

### Page UI

**`apps/web/src/routes/(app)/risk/+page.svelte`** — replace `PlaceholderCard`:

- **Header**: `<h1>Risk</h1>` + small kill-switch indicator (`Badge` `destructive` when `kill_switch_active: true`, `success` when false). Last-updated timestamp from `fetched_at` ISO 8601 in `<dt>`/`<dd>` pattern.
- **Caps card** (NEW component `RiskCapsCard`): grid of 5 caps (`per_trade_pct`, `daily_loss_pct`, `weekly_loss_pct`, `max_open_positions`, `max_drawdown_pct`). Percentages formatted via `formatPercent` from `$lib/portfolio/format.ts` (already shipped); `max_open_positions` is integer → render as-is.
- **State + utilisation card** (NEW component `RiskUtilisationCard`): for each of `daily_loss`, `weekly_loss`, `max_drawdown` (the 3 keys in `utilisation`), render a horizontal utilisation bar:
  - Label (Spanish): "Pérdida diaria", "Pérdida semanal", "Drawdown máx."
  - Bar: width = `min(utilisation[key] / cap_for_key, 1.0) * 100%`. OKLCH colour: `--success` <0.5, `--accent` 0.5-0.8, `--destructive` >0.8.
  - Right-side value: `formatPercent(utilisation[key])` of `formatPercent(cap_pct)` (e.g. "2.1% / 5.0%").
- **Open positions count**: numeric badge ("3 / 5") matching `state.open_positions_count` / `caps.max_open_positions`.
- **Capital**: `formatMoney(state.capital, "USD")` displayed as a stat below.
- **Empty state**: when `loadError === null` AND every utilisation is 0 AND `state.capital === "0"` → `EmptyState` "Sin actividad de riesgo aún. El estado se inicializará cuando arranque el daemon."
- **Error state**: `loadError` → red alert.

### New components

- **`apps/web/src/lib/components/RiskCapsCard.svelte`** — props `{ caps: CapsDTO }`. 5-cell grid card.
- **`apps/web/src/lib/components/RiskUtilisationCard.svelte`** — props `{ utilisation: Record<string, string>, caps: CapsDTO }`. Bar generator pure: `utilisationBarColour(ratio: number): 'success' | 'accent' | 'destructive'` in `$lib/risk/colour.ts`.

### TS types

`apps/web/src/lib/risk/types.ts` — mirrors of `CapsDTO`, `StateDTO`, `RiskStateResponse` (Decimal-as-string).

### Tests

- **`apps/web/tests/risk-page.test.ts`** (vitest):
  1. Happy path — full payload renders caps card + utilisation bars + kill-switch indicator.
  2. Empty/zero state → `EmptyState` rendered.
  3. API 503 → `loadError` alert.
  4. Kill switch active → indicator shows `destructive`.
  5. Utilisation 0.9 (90%) on daily_loss → bar has `destructive` colour class.

- **`apps/web/tests/risk-colour.test.ts`** (vitest, pure): `utilisationBarColour` returns `success`/`accent`/`destructive` for the 3 ranges.

### Storybook

3 variants each for `RiskCapsCard.stories.ts` + `RiskUtilisationCard.stories.ts` (idle / approaching cap / kill-switch).

## Out of scope

- **`POST /risk/override`** UI — separate slice (`risk-override-ui`); requires the proposal-id + risk-eval-id flow which only makes sense after `/approvals` UI ships.
- **SSE realtime** (`/stream/risk/events`) — page is `load`-fn driven for v1; `risk-sse-realtime` is a separate slice.
- **Per-proposal `per_trade` utilisation** — backend says this is per-evaluation event; surfaces in `/approvals` UI, not here.
- **Historical drawdown chart** — overlaid sparkline of `peak_to_trough_drawdown_pct` over time. v1.5.
