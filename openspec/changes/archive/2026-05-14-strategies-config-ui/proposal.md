# Proposal: strategies-config-ui

> **Wire the `/strategies` dashboard tab to consume the 4 CRUD endpoints shipped by PR #142** — `GET /strategies` (list) + `GET /strategies/{symbol}` (read) + `PUT /strategies/{symbol}` (upsert) + `DELETE /strategies/{symbol}` (soft-disable). Today the UI is a `PlaceholderCard`. This slice replaces it with a list view + an edit form, completing the third dashboard tab (after `/trades` α + `/portfolio` dashboard).

## Why

Backend shipped in [[trading-routes-portfolio-strategies-bodies]] (PR #142). 4 endpoints, full CRUD pattern (soft-delete via `DELETE` → `enabled=False`). The UI tab is the only piece missing.

The pattern continues from α + portfolio: `+page.server.ts` server-load + cookie forwarding, reuse `EmptyState` / `Badge` / `DataTable`, honest "—" for null fields. New here vs read-only tabs: a form (the upsert) + an action button (the soft-delete).

Available strategy kinds in v1 (per `apps/api/src/iguanatrader/contexts/trading/strategies/`):
- `donchian_atr` — params `{ lookback: int, atr_mult: float }`
- `sma_cross` — params `{ fast: int, slow: int }`

`StrategyConfigIn` accepts arbitrary `params: dict[str, Any]` (Pydantic v2 `extra="forbid"` only at DTO level; the dict itself is open). v1 UI surfaces a `strategy_kind` dropdown + a generic JSON-textarea params editor (validates on submit via `JSON.parse`). Per-kind structured forms are a v1.5 follow-up (`strategies-typed-forms`).

## What

### Page-level server load (list)

**`apps/web/src/routes/(app)/strategies/+page.server.ts`** (NEW). Single fetch:

- `GET ${API_BASE_URL}/api/v1/strategies` → `StrategyConfigListOut`.

Returns `{ strategies: StrategyConfigOut[], loadError: string | null }`. Cookie forwarding identical to α's `+page.server.ts`.

### Page UI (list)

**`apps/web/src/routes/(app)/strategies/+page.svelte`** — replace `PlaceholderCard` body:

- **Header bar**: page `<h1>` + button "Nueva estrategia" → navigates to `/strategies/new`.
- **Table** (reuses existing `DataTable` from α): columns `Symbol`, `Strategy kind`, `Enabled` (Badge: `success` when true, `mute` when false), `Version`, `Updated`, `Actions`. Row click → `/strategies/{symbol}` for edit. The Actions column has two buttons inline:
  - "Editar" → `goto('/strategies/{symbol}')`
  - "Deshabilitar" (only shown when row.enabled) → confirm + `DELETE` + reload (or surface error).
- **Empty state**: when `strategies.length === 0` → `EmptyState` card: "Sin estrategias configuradas. Crea una para empezar a generar señales." + hint linking to docs/strategies.
- **Error state**: `loadError` → red alert.

### Edit/upsert form route

**`apps/web/src/routes/(app)/strategies/[symbol]/+page.server.ts`** (NEW). Two-mode load:

- If `params.symbol === 'new'` → return `{ mode: 'new', strategy: null, loadError: null }`.
- Else: `GET ${API_BASE_URL}/api/v1/strategies/{symbol}` → `StrategyConfigOut`. 404 → `loadError`.

Plus a SvelteKit `Actions` block (`export const actions`) for `upsert` + `disable`:
- `upsert`: validates form fields, `PUT ${API_BASE_URL}/api/v1/strategies/{symbol}` with `{ strategy_kind, params, enabled }`, on success redirect to `/strategies`, on 4xx return `{ formError: string, fieldErrors: {...} }`.
- `disable`: `DELETE ${API_BASE_URL}/api/v1/strategies/{symbol}`, on success redirect to `/strategies`.

### Form UI

**`apps/web/src/routes/(app)/strategies/[symbol]/+page.svelte`** (NEW):

- Header: "Nueva estrategia" or "Editar estrategia: {symbol}".
- Form fields:
  - `symbol` (only in `mode: 'new'`; text input, required, uppercase A-Z + numbers; pattern `^[A-Z0-9]{1,16}$` per IBKR symbol conventions).
  - `strategy_kind` (select dropdown, options: `donchian_atr` + `sma_cross`).
  - `params` (textarea; default JSON placeholder shown per `strategy_kind` choice via reactive `$derived` watching the dropdown — e.g. selecting `donchian_atr` populates `{"lookback": 20, "atr_mult": 2.0}` as the textarea default if it's empty).
  - `enabled` (checkbox, default true).
- Submit button: "Guardar" (sends `upsert` form action).
- Cancel link: → `/strategies`.
- If edit mode + row exists + `enabled === true` → also render a separate "Deshabilitar" button (form action `disable`) below the form, separated by a `<hr>` + small destructive note ("Esto pondrá la estrategia en estado disabled — no borra el config ni cierra posiciones abiertas").
- Field errors render inline below each field (`form?.fieldErrors?.symbol` etc); form-level errors render as a red banner above.
- JSON validation on submit: `params` textarea is parsed; on parse error → `fieldErrors.params = "JSON inválido: ..."` (validated client-side before POST to save the round-trip; backend also validates per Pydantic).

### Reusable form pieces

**`apps/web/src/lib/components/forms/TextInput.svelte`** (NEW) — `{ name, label, value, type='text', required, pattern?, helpText?, error? }`. Renders a label + input + optional helptext + inline error. Reusable for the next form-bearing slices.

**`apps/web/src/lib/components/forms/Select.svelte`** (NEW) — `{ name, label, value, options: { value, label }[], error? }`.

**`apps/web/src/lib/components/forms/Textarea.svelte`** (NEW) — `{ name, label, value, rows=8, monospace=true, error? }`. Monospace + slight padding-bottom + line-numbers indicator optional.

**`apps/web/src/lib/components/forms/Checkbox.svelte`** (NEW) — `{ name, label, checked }`.

(These form primitives are intentional hoists for the next slices that will gain forms — risk threshold editor, costs budget editor, etc.)

### TS types

`apps/web/src/lib/strategies/types.ts` — mirrors of `StrategyConfigOut`, `StrategyConfigIn`, `StrategyConfigListOut`. Same pattern as `$lib/trades/types.ts` + `$lib/portfolio/types.ts`.

### Tests

- **`apps/web/tests/strategies-list-page.test.ts`** (vitest):
  1. Happy path — mocked list → table rows + side/state badges + Actions buttons rendered.
  2. Empty list → `EmptyState` rendered.
  3. API 503 → `loadError` alert.
  4. Click "Editar" → navigates to `/strategies/{symbol}`.
  5. Click "Deshabilitar" + confirm → `DELETE` request fires; row disappears after reload.

- **`apps/web/tests/strategies-form-page.test.ts`** (vitest):
  1. New mode: empty form, symbol input present.
  2. Edit mode: form pre-filled from API.
  3. Selecting `strategy_kind` → params textarea shows the kind's default JSON shape (only when textarea was previously empty).
  4. Submit with invalid JSON → `fieldErrors.params` rendered.
  5. Submit with invalid symbol pattern → `fieldErrors.symbol` rendered.
  6. Successful upsert → redirect to `/strategies` (mock `redirect` from SvelteKit).
  7. Disable button click → confirm + `DELETE` + redirect.
  8. API 404 on edit load → `loadError` rendered.

### Storybook

3 variants each for `TextInput`, `Select`, `Textarea`, `Checkbox` (default / with-error / disabled). Reuse + extend the OKLCH styling from the existing components.

## Out of scope

- **Per-kind structured forms** — `donchian_atr` and `sma_cross` get a generic JSON textarea in v1. v1.5 follow-up (`strategies-typed-forms`) generates per-kind fields from a TS schema map.
- **Strategy kind catalogue endpoint** — frontend hard-codes the 2 kinds in the dropdown. When v1.5+ adds more kinds, a `GET /strategies/catalogue` endpoint surfaces them. For 2 kinds, hard-coding is fine.
- **Multi-kind-per-symbol UI** — backend supports it (composite UNIQUE is `(tenant_id, strategy_kind, symbol)`); v1 GET-by-symbol picks oldest enabled + the form upserts the kind selected in the dropdown. Multi-kind editor is v1.5 (`strategies-multi-kind-ui`).
- **Live preview / dry-run** — the `/strategies` page does NOT trigger a propose iteration; that's `trading run` daemon territory. v2 could add a "Dry-run on last 30d bars" button.
- **History / audit log of changes** — `version` column bumps on each PUT but the UI shows only the current version. A "Cambios recientes" view is v1.5.
- **Hard delete** — only soft-disable in v1 (backend doesn't ship hard delete on purpose; preserves audit trail).
