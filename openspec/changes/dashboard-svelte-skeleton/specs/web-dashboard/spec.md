## ADDED Requirements

### Requirement: `(app)` route group renders the canonical authenticated shell

The system SHALL extend `apps/web/src/routes/(app)/+layout.svelte` to render the authenticated shell — Sidebar (left), TopBar (top, with theme toggle + ConnectionIndicator + reserved KillSwitchButton slot), main content slot. The cookie hook in `apps/web/src/hooks.server.ts` (slice 4 contract, consumed unchanged) SHALL gate the route group: unauthenticated requests to any `(app)/*` path 302 to `/login?redirect_to=<originating>`. The existing `(app)/+layout.server.ts` SHALL expose `data.user` to the layout via SvelteKit's standard load-function pattern.

#### Scenario: Unauthenticated request to (app) route redirects to /login

- **WHEN** a user without a valid session cookie navigates to `/portfolio`
- **THEN** the response is `302 Found` with `Location: /login?redirect_to=%2Fportfolio`
- **AND** the layout's render code is never invoked (hook redirects pre-render)

#### Scenario: Authenticated request renders the shell

- **WHEN** a user with a valid session cookie navigates to `/`
- **THEN** the response renders Sidebar + TopBar + content slot
- **AND** `data.user` is populated from `event.locals.user` (slice 4 hook output)
- **AND** the active sidebar item is highlighted via prefix-match against `$page.url.pathname`

#### Scenario: KillSwitchButton slot is reserved but empty in W1

- **WHEN** the TopBar renders in W1
- **THEN** the slot for KillSwitchButton exists in the markup (`<div data-slot="kill-switch" />`) but renders no button
- **AND** slice K1 fills the slot in a follow-up PR without editing `TopBar.svelte`

### Requirement: Sidebar enumerates routes dynamically via `import.meta.glob` — anti-collision pattern

The system SHALL provide `apps/web/src/lib/components/nav/Sidebar.svelte` that enumerates all `(app)/*/+page.svelte` modules at compile time via `import.meta.glob('/src/routes/(app)/*/+page.svelte', { eager: true })`. Each route module MAY export a `meta: { label, icon, order, requiresRole? }` const. Routes without `meta` SHALL fall back to a kebab-cased path label + default icon + order 100. Sorting SHALL be `(meta.order, href)` ascending.

#### Scenario: Drop a new (app)/<name>/+page.svelte and Sidebar enumerates it

- **WHEN** a developer drops `apps/web/src/routes/(app)/risk/+page.svelte` exporting `meta = { label: 'Risk', icon: 'gauge', order: 60 }`
- **AND** the dev server reloads (or the app is rebuilt)
- **THEN** the Sidebar renders a new "Risk" link at position 60 (between order 50 and 70 entries)
- **AND** no edit to `Sidebar.svelte` is required

#### Scenario: Route without meta export falls back to defaults

- **WHEN** a developer drops `apps/web/src/routes/(app)/foobar/+page.svelte` without a `meta` export
- **THEN** the Sidebar renders a "Foobar" link at order 100 with the fallback `circle` icon
- **AND** no warning surfaces (the route is reachable; the rendering is just ungeometric)

#### Scenario: Two routes with the same order break ties alphabetically

- **WHEN** two routes both export `meta.order = 50`
- **THEN** they render in alphabetical order of their `href` values

#### Scenario: Sidebar collapsed state persists across reloads

- **WHEN** a user toggles the Sidebar collapsed via the toggle button
- **AND** reloads the page
- **THEN** the Sidebar renders in the collapsed state on the next mount
- **AND** the state is read from `localStorage` via the `nav` store

### Requirement: `+error.svelte` renders RFC 7807 Problem from `$page.error`

The system SHALL provide `apps/web/src/routes/+error.svelte` that reads `$page.error` and renders the RFC 7807 Problem body. The Problem type SHALL be sourced from `@iguanatrader/shared-types` (slice 5's typegen output) with a defensive local fallback in `apps/web/src/lib/types/problem.ts` for the placeholder pre-typegen state.

#### Scenario: Recoverable error (4xx) renders with action hint

- **WHEN** a SvelteKit load function calls `error(404, { type: 'urn:iguanatrader:error:not-found', title: 'Not Found', status: 404, detail: 'Trade ID 999 does not exist' })`
- **THEN** the `+error.svelte` renders the title + detail + a "Go home" link
- **AND** the type URI badge displays `urn:iguanatrader:error:not-found`

#### Scenario: Unrecoverable error (5xx) shows correlation ID + copy button

- **WHEN** a load function rejects with `error(500, { ..., correlation_id: 'req-abc-123' })`
- **THEN** the `+error.svelte` renders the title + a generic body ("Unexpected server error") + the correlation ID + a copy-to-clipboard button
- **AND** the raw `detail` field is shown if present (defensive — slice 5's handler omits raw exception text per its contract)

#### Scenario: Auth error (401) is intercepted by hooks.server.ts before reaching +error.svelte

- **WHEN** a `(app)/*` route's load function would return 401
- **THEN** the cookie hook (slice 4 contract) intercepts and 302s to `/login?redirect_to=...`
- **AND** the `+error.svelte` does NOT render (the hook fired first)

### Requirement: Base stores expose reactive cross-cutting state

The system SHALL provide `apps/web/src/lib/stores/{auth,nav,theme,connection}.ts` as singleton class instances using Svelte 5 runes (`$state`, `$derived`, `$effect`). The `auth` store SHALL hydrate from `(app)/+layout.server.ts` `data.user`. The `nav` store SHALL persist `collapsed` to `localStorage`. The `theme` store SHALL read `prefers-color-scheme` + `localStorage` and apply `data-theme` to `<html>`. The `connection` store SHALL aggregate per-stream SSE health.

#### Scenario: auth store hydrates from layout data

- **WHEN** the `(app)` layout mounts
- **AND** `data.user` is `{ id: 'u-1', email: 'arturo@example.com', role: 'admin' }`
- **THEN** `authStore.user` reflects that value reactively in any consuming component

#### Scenario: theme store applies data-theme attribute on mount

- **WHEN** the user opens the app for the first time
- **AND** `prefers-color-scheme: dark` is set
- **THEN** `<html data-theme="dark">` is set
- **AND** `localStorage['iguanatrader:theme'] = 'dark'` is persisted

#### Scenario: connection store aggregates per-stream state

- **WHEN** the equity SSE stream is `'open'` and the costs SSE stream is `'reconnecting'`
- **THEN** `connectionStore.global` is `'reconnecting'` (worst-case wins)
- **AND** the TopBar `ConnectionIndicator` renders amber + "Reconnecting"

### Requirement: `useFetch` composable always sends credentials and parses RFC 7807 errors

The system SHALL provide `apps/web/src/lib/composables/useFetch.ts` that wraps native `fetch` with `credentials: 'include'`, `Accept: application/json, application/problem+json`, and `Content-Type: application/json` for non-GET requests. On 4xx/5xx responses with `Content-Type: application/problem+json`, the composable SHALL parse the body as `Problem` and return it (NOT throw). On other transport errors (network, malformed JSON), the composable SHALL throw.

#### Scenario: Successful GET returns typed payload

- **WHEN** a page calls `await useFetch<TradesList>('/api/v1/trades')`
- **AND** the server returns 200 with `application/json`
- **THEN** the composable returns the parsed body typed as `TradesList`
- **AND** the request was sent with `credentials: 'include'` (cookie auto-attached)

#### Scenario: 4xx response returns Problem object

- **WHEN** a page calls `await useFetch('/api/v1/trades/999')`
- **AND** the server returns 404 with `application/problem+json` body `{ "type": "urn:iguanatrader:error:not-found", "title": "Not Found", "status": 404, "detail": "Trade 999 not found" }`
- **THEN** the composable returns the parsed Problem (NOT throws)
- **AND** the caller pattern-matches on `if ('type' in result && result.type.startsWith('urn:iguanatrader:'))` to distinguish

#### Scenario: Network failure throws

- **WHEN** the SvelteKit dev server is offline
- **AND** a page calls `await useFetch('/api/v1/whatever')`
- **THEN** the composable throws a TypeError ("Failed to fetch")
- **AND** the caller's surrounding try/catch handles it (or the SvelteKit `load` function rejects → `+error.svelte` renders)

### Requirement: `useSSE` composable reconnects on drop with canonical backoff

The system SHALL provide `apps/web/src/lib/composables/useSSE.ts` that wraps `EventSource` with reconnect-on-drop using the canonical backoff `[3, 6, 12, 24, 48]` seconds (matching slice 2's HeartbeatMixin). The composable SHALL update the `connection` store per stream-name with state `'open' | 'reconnecting' | 'closed'`. On component unmount, the caller SHALL call the returned `close()` to cleanly disconnect.

#### Scenario: SSE connection opens and updates connection store

- **WHEN** a page calls `useSSE('equity', { onMessage })`
- **AND** the server's `/api/v1/stream/equity` returns 200 with `text/event-stream`
- **THEN** `connectionStore.streams.equity = 'open'`
- **AND** subsequent messages fire `onMessage(event)`

#### Scenario: SSE drop triggers reconnect with backoff

- **WHEN** an active SSE connection drops (server closes, network blip)
- **THEN** `connectionStore.streams.<name> = 'reconnecting'`
- **AND** the composable retries after 3s, then 6s, 12s, 24s, 48s if each retry fails
- **AND** on successful reconnect, the state returns to `'open'`

#### Scenario: Component unmount closes connection cleanly

- **WHEN** a page mounts a `useSSE('costs', ...)`
- **AND** navigates away (component unmounts)
- **THEN** the caller's `$effect` cleanup invokes the returned `close()`
- **AND** `connectionStore.streams.costs = 'closed'`
- **AND** no further reconnect attempts fire

### Requirement: Domain page stubs render `"loading…"` placeholder + meta export

The system SHALL provide 8 domain page stubs at `apps/web/src/routes/(app)/{research,trades,portfolio,strategies,settings,costs,risk,approvals}/+page.svelte`. Each stub SHALL render `<section aria-busy="true">loading…</section>` and export a `meta` const with `{ label, icon, order }`. Each Wave 3-4 slice that owns the domain SHALL replace the body of its assigned stub without editing the `meta` export (unless the slice has explicit reason to update label/icon/order, documented in the slice's tasks.md).

#### Scenario: All 8 stubs are reachable from Sidebar

- **WHEN** the authenticated dashboard renders
- **THEN** Sidebar enumerates entries for: Portfolio (10), Trades (20), Strategies (30), Research (40), Approvals (50), Risk (60), Costs (70), Settings (80)
- **AND** clicking each navigates to the corresponding route
- **AND** the route renders `"loading…"` until its owner slice replaces the body

#### Scenario: Domain stub passes Lighthouse a11y

- **WHEN** Lighthouse audits a domain stub URL (e.g., `/research`)
- **THEN** the stub's `aria-busy="true"` + `<section>` semantic root + the surrounding shell's nav landmark satisfy a11y rules
- **AND** the a11y score is ≥ 0.95

### Requirement: Lighthouse CI asserts a11y ≥ 0.95 across authenticated-shell URLs

The system SHALL update `lighthouserc.cjs` (root, slice 5) to bump `assertions.categories.accessibility` minScore from 0.90 to 0.95 and extend the URL list to include `/`, `/research`, `/trades`, `/portfolio`, `/strategies`, `/approvals`, `/risk`, `/costs`, `/settings` (in addition to existing `/login`). Authenticated-shell URLs SHALL run with a session cookie set by the lhci collect step (mock-fastapi pattern from slice 4).

#### Scenario: a11y regression in Sidebar fails the workflow

- **WHEN** a developer removes `aria-label` from the Sidebar nav landmark
- **AND** the Lighthouse CI step runs against `/`
- **THEN** the a11y score drops below 0.95
- **AND** the workflow fails with the specific Lighthouse audit ID (`landmark-unique` or similar)

#### Scenario: perf below 0.90 — workflow passes (perf is informational only)

- **WHEN** dev-mode rendering produces a perf score of 65 (no minification)
- **THEN** the Lighthouse step passes (perf assertion stays informational; only a11y < 0.95 fails)

### Requirement: SSE consumer stubs are pre-declared per Wave 2-4 backend slice ownership

The system SHALL provide 7 SSE consumer modules at `apps/web/src/lib/sse/{research,trades,costs,risk,approvals,equity,alerts}.ts`. Each module SHALL export a `connect<Name>Stream(opts)` function wrapping `useSSE` and pointing at `/api/v1/stream/<name>`. Until each backend slice ships its concrete SSE route, the consumer SHALL connect successfully + handle 404 gracefully via `useSSE`'s reconnect-with-backoff (state transitions to `'reconnecting'` then `'closed'` after backoff exhaustion).

#### Scenario: Backend SSE route absent — consumer gracefully closes

- **WHEN** a page calls `connectCostsStream({ ... })` and the backend has not yet shipped `apps/api/src/iguanatrader/api/sse/costs.py`
- **THEN** the consumer attempts connection, receives 404 from the dynamic-discovery loop
- **AND** `connectionStore.streams.costs` cycles `'reconnecting'` → `'closed'` after backoff exhaustion
- **AND** no exception escapes to the calling page (the page renders `"loading…"`)

#### Scenario: Backend SSE route lands — consumer auto-attaches

- **WHEN** slice O1 ships `apps/api/src/iguanatrader/api/sse/costs.py` exporting `router: APIRouter`
- **AND** the SvelteKit dev server is restarted
- **AND** a page calls `connectCostsStream({ ... })`
- **THEN** the consumer attaches; messages flow; `connectionStore.streams.costs = 'open'`
- **AND** no edit to `lib/sse/costs.ts` was required (the wrapper was already in place from W1)
