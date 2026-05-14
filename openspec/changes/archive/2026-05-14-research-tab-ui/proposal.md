# Proposal: research-tab-ui

> **Replace the `/research` `PlaceholderCard` with a watchlist landing page.** Backend was wired by slices R3–R6 (5 endpoints under `/api/v1/research/*`); the `[symbol]` detail sub-route already exists in `apps/web/src/routes/(app)/research/[symbol]/`. What's missing: a landing page with a symbol-search input + recent-symbol history that navigates to the detail.

## Why

Last dashboard tab still on `PlaceholderCard` after the 6 prior dashboard slices (trades, portfolio, strategies, risk, costs, approvals). Backend is fully shipped. Detail route at `/research/[symbol]` already works. This slice just adds the entry-point landing.

No "list all symbols with briefs" endpoint exists — the backend is symbol-keyed (`/briefs/{symbol}`). For MVP: search-input + localStorage-backed recent-symbols list. Operators jump to detail via input or recent. v1.5 (`research-watchlist-endpoint`) could add a server-backed watchlist if needed.

## What

### Page UI

**`apps/web/src/routes/(app)/research/+page.svelte`** — replace `PlaceholderCard` with:

- **Header**: `<h1>Research</h1>`.
- **Search card** (NEW component `SymbolSearchCard`): a centered card with:
  - `TextInput` (reuse from `forms/`) labeled "Symbol", pattern `^[A-Z0-9]{1,16}$`, placeholder "SPY".
  - "Buscar brief" submit button → on submit, validates pattern + navigates to `/research/{symbol}`.
  - On invalid input → inline error "Symbol inválido. Usa 1-16 caracteres A-Z + dígitos."
- **Recent symbols list** (NEW component `RecentSymbolsList`):
  - Pulls from `localStorage.getItem('iguanatrader.research.recent')` (JSON array of up to 8 symbols).
  - On detail-page navigation (`/research/[symbol]`), the detail page records the visited symbol in localStorage (existing detail page edit; small touch).
  - Renders as a horizontal pill list: each pill is a `<a href="/research/{symbol}">{symbol}</a>` styled like `Badge accent`.
  - When list is empty: render `EmptyState` "Sin búsquedas recientes. Empieza buscando un symbol arriba."

### Detail-page hook

**`apps/web/src/routes/(app)/research/[symbol]/+page.svelte`** — small edit to record the visited symbol:

- On mount (`$effect`), push the current `$page.params.symbol` to the front of `iguanatrader.research.recent` localStorage list, dedupe, cap at 8.

### Reusable component

**`apps/web/src/lib/components/SymbolSearchCard.svelte`** — `{ onSubmit?: (symbol: string) => void }`. Reuses `TextInput` + handles pattern validation. Default submit handler navigates to `/research/{symbol}` via `goto`. Reusable for any future symbol-keyed search (e.g., per-symbol portfolio drill-down).

**`apps/web/src/lib/components/RecentSymbolsList.svelte`** — `{ storageKey: string, max?: number, label?: string }`. Reads from localStorage on mount via `$state` + writes on `recordSymbol(symbol)` static method. Reusable for any "recent X" pattern.

### Pure helpers

**`apps/web/src/lib/research/recent.ts`** (NEW):
- `readRecent(storageKey: string): string[]` — JSON.parse with fallback to `[]` on parse error.
- `recordRecent(storageKey: string, symbol: string, max: number = 8): string[]` — pure function (no DOM) that takes a list + new symbol, dedupes, caps. The component calls it then `localStorage.setItem`.

Unit-testable without DOM (the impure localStorage glue is in the component).

### Tests

- **`apps/web/tests/research-tab.test.ts`** (vitest):
  1. Empty localStorage → `EmptyState` rendered in `RecentSymbolsList`.
  2. Valid symbol entered → navigates to `/research/{symbol}` (mock `goto`).
  3. Invalid symbol pattern → inline error rendered.
  4. localStorage seeded with 3 symbols → 3 pills rendered.
  5. localStorage corrupted (non-JSON) → falls back to empty (no crash).

- **`apps/web/tests/research-recent.test.ts`** (vitest, pure): `readRecent` + `recordRecent` (dedupe / cap / new symbol prepended / corrupted input).

### Storybook

3 variants each for `SymbolSearchCard.stories.ts` + `RecentSymbolsList.stories.ts` (default / with-error / empty).

## Out of scope

- **Server-backed watchlist** (`GET /research/watchlist`) — v1.5 if operators ask for cross-device sync.
- **Bulk refresh from landing** — currently each symbol's detail page has its own refresh button.
- **Brief preview on hover** — would need an additional fetch per pill. Defer.
- **Symbol auto-complete** — would need a symbols-catalogue endpoint. v1.5.
- **Touching the detail page beyond the localStorage hook** — the existing `/research/[symbol]/+page.svelte` body stays as it was shipped in R5/R6.
