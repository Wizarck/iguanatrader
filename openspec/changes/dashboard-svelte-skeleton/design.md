## Context

Slice W1 plants the **frontend twin of slice 5's anti-collision foundation**. Wave 0+1 cumulative state at slice-W1 start:

- Slice 1 `bootstrap-monorepo` ✅ — `apps/web/` workspace declared.
- Slice 4 `auth-jwt-cookie` ✅ — SvelteKit scaffold + `(auth)/login/+page.{svelte,server.ts}` + `(app)/+layout.{server.ts,svelte}` stub + `(app)/portfolio/+page.svelte` placeholder + `hooks.server.ts` cookie gate + `tests-e2e/mock-fastapi.mjs` dual-server pattern + 4 visual baselines under `tests-e2e/screenshots/`.
- Slice 5 `api-foundation-rfc7807` ✅ — `packages/shared-types` workspace package (placeholder `export {}` until typegen bot regenerates), `/api/v1/stream/*` SSE prefix declared, `Problem` Pydantic v2 model + RFC 7807 contract, `lighthouserc.cjs` baseline (a11y ≥ 0.9, perf informational), Lighthouse CI step in `openapi-types.yml` runs `pnpm dev` against `/login`.

The challenge is **structural and ergonomic, not algorithmic**. Wave 3-4 has 7 slices that touch UI (R5, R6, T4, K1, O1, P1, O2) plus three (T2, T3, R2-R4) that don't. If each UI-touching slice had to register its route in a sidebar nav array, parallel merges race. The frontend twin of slice 5's `pkgutil.iter_modules` is `import.meta.glob('/src/routes/(app)/*/+page.svelte', { eager: true })` — Vite resolves this at build time, no runtime cost, deterministic alphabetical order, and the contract is "drop a `+page.svelte`; the rest is automatic." The same logic applies to SSE consumer stubs (one stub per `/api/v1/stream/<name>` mount declared by slice 5 + future slices) and to base composables (`useFetch` / `useSSE`) that every Wave 3-4 page will consume.

The Lighthouse a11y bump (0.90 → 0.95) is a slice 5 design Q2 deferred decision — slice 5 set 0.90 because the surface was just `/login`; W1 lands the dashboard skeleton and earns the bump, since 8 stub pages + sidebar + error boundary + top bar give Lighthouse enough surface to assert tighter a11y rules. Performance score stays informational (dev-mode Lighthouse penalises non-minified bundles; switching to `pnpm preview` is a follow-up — see D9 trade-off).

## Goals / Non-Goals

**Goals:**
- Land the `(app)` authenticated shell as the canonical operational layout (Sidebar + top bar + content + connection indicator) so every Wave 3-4 UI slice fills the content slot only.
- Plant the `Sidebar.svelte` dynamic enumeration via `import.meta.glob` so each Wave 3-4 slice that adds a `(app)/<name>/+page.svelte` is picked up automatically with zero edits to `Sidebar.svelte`.
- Plant the `+error.svelte` global boundary that renders RFC 7807 `Problem` typed via `@iguanatrader/shared-types` so any unhandled SvelteKit `error()` or load-function rejection renders consistently.
- Plant the base stores (auth, nav, theme, connection) + composables (useFetch with credentials, useSSE with backoff reconnect) that every Wave 3-4 page consumes — no per-slice fetch / SSE wiring duplication.
- Plant 7 SSE consumer stubs (`research`, `trades`, `costs`, `risk`, `approvals`, `equity`, `alerts`) targeting `/api/v1/stream/<name>` mounts — backend slices populate these as their own scope; W1 only ships the typed wrappers + reconnect contract.
- Plant 8 domain page stubs rendering `"loading…"` placeholder + `meta` export (route metadata) so Sidebar enumerates them — each Wave 3-4 slice replaces the body, never touches Sidebar.
- Bump Lighthouse a11y minScore from 0.90 → 0.95 (per slice 5 Q2 deferred answer) + extend the URLs list to include authenticated-shell stubs.
- Extend slice 4's Playwright dual-server pattern with new spec files (dashboard-skeleton, sidebar-dynamic, error-boundary, theme-toggle) + visual baselines under `tests-e2e/screenshots/`.
- Plant Tailwind 4.x + OKLCH design tokens locked in `docs/ux/components.md` §0.3 so every Wave 3-4 component consumes the same token set.

**Non-Goals:**
- No concrete content for any of the 8 domain pages (research, trades, portfolio, strategies, settings, costs, risk, approvals). Each Wave 3-4 slice plants its own.
- No KillSwitchButton component (K1 owns it; W1 only leaves a slot in the top bar).
- No Storybook + per-component visual catalogue (deferred — components.md §1 lists stories but does not require them this slice).
- No light-mode toggle UI surface (locked tokens are dark-first; light derivation deferred — `theme` store reads `prefers-color-scheme` + `localStorage` and applies `data-theme="dark"`, but no UI toggle).
- No RBAC enforcement on Sidebar items (T4 + role-aware backend).
- No backend changes — `apps/api/`, `packages/shared-types/` typegen output, `apps/openbb-sidecar/` are read-only.
- No new SSE backends — slice 5 declared the prefix; W1 stubs the consumers; backend slices populate their own routes.

## Decisions

### D1. `(app)` layout group is the canonical authenticated shell — no separate `<DashboardLayout>` component

**Decision**: `apps/web/src/routes/(app)/+layout.svelte` itself renders the full authenticated shell: Sidebar (left), TopBar (top — with theme toggle + connection indicator + KillSwitchButton slot), main content slot (`{@render children()}`). The shell is NOT a separate `lib/components/layout/DashboardLayout.svelte` that the layout file imports — the layout file IS the shell. The cookie hook in `hooks.server.ts` (slice 4) gates the route group; the existing `(app)/+layout.server.ts` (slice 4) already exposes `data.user`; W1 reads it via `let { data } = $props()` in the layout's `<script>` block + passes to Sidebar / TopBar.

**Alternatives considered**:
- **Separate `DashboardLayout.svelte` component imported by the layout file**: extra indirection, no reuse benefit (only one (app) layout), harder to debug SvelteKit-specific concerns (slot composition, error boundaries).
- **Layout group as a `<SvelteKitShell>` wrapper at the root layout**: mixes auth + non-auth surfaces, breaks SvelteKit's route-group conventions.

**Rationale**: SvelteKit's `(group)` route convention is a direct contract — layouts are co-located with the routes they wrap. Putting the shell inline is idiomatic and makes the auth gate + shell one cohesive unit. Aligns with `docs/ux/components.md` §2.1.

**Implementation note**: the existing slice 4 stub layout (`{@render children()}` only) is extended in place. The slice 4 +layout.server.ts is consumed unchanged. The slice 4 hooks.server.ts is consumed unchanged.

### D2. Sidebar dynamic enumeration via `import.meta.glob` with `eager: true` + per-route `meta` export — anti-collision crítico

**Decision**: `apps/web/src/lib/components/nav/Sidebar.svelte` enumerates routes at compile time via:

```ts
const routeModules = import.meta.glob('/src/routes/(app)/*/+page.svelte', { eager: true });
```

Each route module MAY export a top-level `meta` const:

```ts
export const meta = {
  label: 'Portfolio',
  icon: 'briefcase',           // Lucide icon name (per components.md §0.5)
  order: 10,                   // sort key, default 100
  requiresRole: 'admin'        // optional; not enforced in W1, T4 wires
} as const;
```

Routes without `meta` get a fallback: `label = capitalize(routePathSegment)`, `icon = 'circle'`, `order = 100`. Sorted by `(order, href)`. Rendering uses `$derived` rune over a tuple of `(href, meta)` extracted from the glob keys.

**Alternatives considered**:
- **Static SidebarItems array in `Sidebar.svelte`**: every slice edits the array, every PR conflicts. Rejected (anti-collision violation).
- **Static SidebarItems array in a `lib/nav/registry.ts`**: same problem — registry file edits race.
- **Server-side discovery via SvelteKit's filesystem routing API**: SvelteKit doesn't expose a stable runtime route inventory; `import.meta.glob` is Vite's documented pattern.
- **`import.meta.glob` with `eager: false` (lazy)**: doesn't enable build-time meta resolution; sidebar would need a mount-time loop with await. Rejected — eager is fine for ~10 routes and gives synchronous render.

**Rationale**: `import.meta.glob` is Vite stdlib + zero runtime cost (resolved at build) + deterministic alphabetical key order + supports the meta-export contract cleanly. The contract is "add a `(app)/<name>/+page.svelte` exporting `meta`; the rest is automatic." Mirrors slice 5's `pkgutil.iter_modules` pattern shape. This is the ONE critical anti-collision mechanism W1 ships.

**Discoverability rule**: if a route's module does not export `meta`, the Sidebar still renders the link with the fallback (no warning — the route is reachable, the label is just unstyled). If two routes export the same `order`, ties break alphabetically by `href`. Documented in the `meta`-exporting domain stubs that W1 plants.

**Edge case**: SvelteKit auth + non-auth route groups don't share a glob — slices outside `(app)` (e.g., a future `(public)/landing`) won't appear in the auth Sidebar. Verified by the slice 4 `(auth)/login` route which is excluded from the glob pattern.

### D3. `+error.svelte` renders RFC 7807 `Problem` from shared-types, with type-only fallback for pre-typegen state

**Decision**: `apps/web/src/routes/+error.svelte` reads `$page.error` (SvelteKit's per-route error context) and renders a `Problem`-shaped UI: `type` URI badge, `title`, `status`, `detail`, optional `instance` + `correlation_id`. The Problem type comes from:

```ts
import type { components } from '@iguanatrader/shared-types';
type Problem = components['schemas']['Problem'];
```

Because `packages/shared-types/src/index.ts` is a placeholder (`export {}`) until the typegen bot regenerates it on the next backend push that touches DTOs (per slice 5 archive task 4.3 + D5), W1 ships a **defensive local fallback type** in `apps/web/src/lib/types/problem.ts` matching slice 5's `Problem` schema field-for-field. The error component imports the fallback if `components['schemas']['Problem']` is `unknown` (TypeScript's structural type system handles this without conditionals — both shapes have the same fields). Once the typegen bot lands real types, the fallback becomes a no-op alias.

**Alternatives considered**:
- **Hard-import from shared-types only**: svelte-check fails until the typegen bot lands real types — blocks the slice on a bot commit that may not arrive in this slice's PR cycle.
- **Inline the Problem interface in `+error.svelte`**: duplicates slice 5's contract; drift risk.
- **Define Problem in `app.d.ts`**: mixes app-wide ambient types with concrete API contracts; muddles ownership.

**Rationale**: defensive shim with single source of truth in slice 5's spec; svelte-check stays green pre- and post-typegen; the cost is 6 lines of boilerplate in `lib/types/problem.ts`. Documented as transient in `docs/gotchas.md`.

**Render variants** (per components.md §2.3):
- `recoverable` (status < 500): action hint based on type URI (e.g., `urn:iguanatrader:error:auth` → "Sign in" link; `urn:iguanatrader:error:not-found` → "Go home" link).
- `unrecoverable` (status ≥ 500): correlation ID (from `instance` or a custom field) + copy-to-clipboard button + "Try again" link.

**Edge case**: 401 from `(app)/*` is intercepted by `hooks.server.ts` → redirected to `/login?redirect_to=<current>`. The `+error.svelte` only renders for errors that escape the cookie hook (e.g., load-function `error(404)`, `error(500)`, network failures during load).

### D4. Stores: `auth`, `nav`, `theme`, `connection` — plain Svelte 5 runes, NOT a state library

**Decision**: stores live in `apps/web/src/lib/stores/{auth,nav,theme,connection}.ts`. Each is a `class` with `$state`/`$derived` runes and a singleton export, NOT a `writable` store from `svelte/store` (Svelte 5 runes are the canonical state primitive). Shape:

- `auth.ts` — `class AuthStore { user = $state<App.Locals['user'] | null>(null); }`. Hydrated from `(app)/+layout.server.ts` `data.user` on mount via a `$effect` in the layout.
- `nav.ts` — `class NavStore { collapsed = $state(false); activeHref = $state<string>('/'); ... }`. Persisted to `localStorage` via `$effect`.
- `theme.ts` — `class ThemeStore { current = $state<'dark' | 'light'>('dark'); ... }`. Reads `prefers-color-scheme` + `localStorage`. Applies `data-theme` to `<html>` via `$effect`.
- `connection.ts` — `class ConnectionStore { streams = $state<Record<string, 'open' | 'reconnecting' | 'closed'>>({}); }`. `useSSE` writes per-stream state; the connection indicator reads aggregate.

**Alternatives considered**:
- **Classic `writable<T>()` from `svelte/store`**: legacy pre-Svelte-5 API; works but mixes paradigms.
- **External library (zustand, jotai)**: dependency for ~150 lines of state; runes do this natively.
- **Store-per-route co-location**: legitimate for slice-specific state (Wave 3-4 slices may); for cross-cutting auth/nav/theme/connection, a singleton-per-store is clearer.

**Rationale**: runes are the canonical Svelte 5 primitive + zero deps + compatible with SvelteKit SSR (`$state` is SSR-safe; `$effect` runs client-only). All four stores are cross-cutting and read by multiple components → singleton per store is right.

### D5. Composables `useFetch` (credentials, RFC 7807 typed errors) + `useSSE` (canonical backoff reconnect)

**Decision**: `apps/web/src/lib/composables/{useFetch,useSSE}.ts`.

`useFetch<TResponse>(url: string, init?: RequestInit): Promise<TResponse | Problem>`:
- Always sets `credentials: 'include'` (cookie hook depends on it).
- Always sets `Accept: application/json, application/problem+json`.
- On 4xx/5xx with `Content-Type: application/problem+json`, parses + returns the `Problem` (NOT throws).
- On other errors, throws.
- Calls onto `API_BASE_URL` from `$lib/config` (slice 4 contract).

`useSSE(name: string, opts: { onMessage?: (e: MessageEvent) => void; onProblem?: (p: Problem) => void; }): { close: () => void }`:
- Wraps `EventSource` (browser-native).
- Backoff `[3, 6, 12, 24, 48]` seconds (slice 2 canonical sequence — frontend mirrors backend HeartbeatMixin contract).
- Updates `connection.ts` store per-stream state.
- Reconnects on `error` event without page reload.
- Closes on component unmount via SvelteKit's `onDestroy` lifecycle (composable returns a `close()` to call from `$effect` cleanup).

**Alternatives considered**:
- **`fetch` + per-page error handling**: every Wave 3-4 page reimplements credentials + Problem parsing. Drift guaranteed.
- **External library (TanStack Query, SWR)**: ~30KB minified for ~100 lines of state. Wave 3-4 may revisit if cache-invalidation gets complex; for W1 the bare composable is enough.
- **WebSocket instead of SSE**: backend declared `/api/v1/stream/*` as SSE (slice 5 D2). Frontend matches.
- **No reconnect on SSE drop**: violates J1 contract (`docs/ux/j1.md` §3 step 1: "After 5s of disconnect: red + persistent banner"). Reconnect is required.

**Rationale**: thin composables, zero deps, mirror slice 2's backend backoff exactly so a developer reading both sides sees the same `[3, 6, 12, 24, 48]` sequence in both places. Documented in `docs/gotchas.md`.

### D6. SSE consumer stubs — 7 modules per slice 5's `/api/v1/stream/*` mounts + Wave 2-4 backend slices' declared streams

**Decision**: `apps/web/src/lib/sse/{research,trades,costs,risk,approvals,equity,alerts}.ts` — 7 typed thin wrappers over `useSSE`. Each module exports a `connect<name>Stream(opts)` function returning the same shape (`{ close }`). Until each backend slice ships its concrete SSE route, these consumers connect successfully but receive no events (the `/api/v1/stream/<name>` mount returns 404 from the dynamic-discovery loop until the module exists, which `useSSE` handles gracefully — sets `connection.streams[<name>] = 'closed'` + retries with backoff).

**Map of 7 stubs to backend slice ownership**:

| Stub | Backend slice that lands the SSE route |
|---|---|
| `research.ts` | R5 `research-brief-synthesis` (`api/sse/research.py`) |
| `trades.ts` | T4 `trading-routes-and-daemon` (`api/sse/equity.py` per slice T4 scope; `trades` may be the same or a separate route — wired flexibly) |
| `costs.ts` | O1 `observability-cost-meter` (`api/sse/costs.py`) |
| `risk.ts` | K1 `risk-engine-protections` (`api/sse/risk.py`) |
| `approvals.ts` | P1 `approval-channels-multichannel` (`api/sse/approvals.py`) |
| `equity.ts` | T4 (`api/sse/equity.py`) |
| `alerts.ts` | O2 `orchestration-scheduler-routines` (`api/sse/alerts.py`) |

**Alternatives considered**:
- **One generic `useSSE` call per page, no stub modules**: each page reimplements the URL + payload-shape contract; Wave 3-4 slices that touch the same stream from multiple pages duplicate.
- **Skip SSE consumers entirely; let each Wave 3-4 slice add its own**: reintroduces collision risk if multiple slices add to a shared `lib/sse/index.ts` registry.

**Rationale**: each stream gets one canonical consumer module; pages call `connect<name>Stream()`; Wave 3-4 slices may extend their own module's payload typing once the backend mounts a real route. The 7 modules are pre-declared because slice 5 already publishes the SSE prefix + Wave 2 backend slices know which streams they own — co-locating the consumer wrapper now prevents duplicate consumers from emerging.

### D7. Domain page stubs (8) render `"loading…"` placeholder + `meta` export — single source of truth for sidebar enum

**Decision**: each of the 8 domain pages — `(app)/{research,trades,portfolio,strategies,settings,costs,risk,approvals}/+page.svelte` — renders:

```svelte
<script lang="ts">
  export const meta = {
    label: 'Portfolio', icon: 'briefcase', order: 10
  } as const;
</script>

<section aria-busy="true">loading…</section>
```

The `meta` export is co-located with the page module so SvelteKit's `import.meta.glob` resolves it together with the component. The `"loading…"` text + `aria-busy="true"` is the contract: when each Wave 3-4 slice replaces the body with real content, the sidebar entry stays untouched (the `meta` export only changes if the slice wants a different label/icon/order — but typically not).

**Alternatives considered**:
- **Empty `+page.svelte`**: SvelteKit warns; less informative for the visual baselines.
- **Per-slice stubs deferred to each Wave 3-4 slice**: defers the sidebar enum test to Wave 3-4; W1 ships a half-built sidebar; defeats the purpose of the anti-collision skeleton.
- **`null` page that returns 503**: misleading to users; "loading…" is honest about the state.

**Rationale**: the 8 stubs are W1's payload — Wave 3-4 slices implement content, not navigation. The `aria-busy="true"` + `"loading…"` is universal Lighthouse-friendly placeholder content (passes a11y assertions).

**Order convention** (per components.md §0.5 + j1.md walkthrough):
- 10: Portfolio (home dashboard summary, primary navigation entry)
- 20: Trades
- 30: Strategies
- 40: Research
- 50: Approvals
- 60: Risk
- 70: Costs
- 80: Settings

Each Wave 3-4 slice's tasks.md will reference this convention.

### D8. Playwright e2e + visual baselines — extend slice 4's dual-server pattern, NOT replace

**Decision**: `apps/web/playwright.config.ts` is extended (not replaced) to pick up the new spec files via existing `testMatch: /.*\.spec\.ts$/` (already a pattern, no edit needed). The existing dual-server (mock-fastapi.mjs + SvelteKit dev) stays intact; W1's new specs reuse the mock auth flow + add stubbed `/api/v1/auth/me` returning a fake user so the cookie gate accepts the session and `(app)/*` renders.

**New specs**:
- `tests-e2e/dashboard-skeleton.spec.ts` — login → land on `/` → assert Sidebar renders all 8 domain links + TopBar renders + ConnectionIndicator renders + each domain page renders `"loading…"` placeholder.
- `tests-e2e/sidebar-dynamic.spec.ts` — light fixture: drop a stub route module via `playwright.config.ts` setup hook (creates a `(app)/_sidebar_test/+page.svelte` ONLY for this test, cleaned up after) → assert it appears in Sidebar with the fallback meta.
- `tests-e2e/error-boundary.spec.ts` — visit a known-failing route stub → assert `+error.svelte` renders Problem-shaped body + correlation ID + copy button.
- `tests-e2e/theme-toggle.spec.ts` — assert `data-theme="dark"` on `<html>` + theme persists across reload (localStorage check).

**Visual baselines** (`tests-e2e/screenshots/`):
- `05-dashboard-empty-shell.png` — sidebar expanded + 8 stubs rendered + topbar.
- `06-dashboard-sidebar-collapsed.png` — collapsed variant.
- `07-error-boundary-404.png` — recoverable error.
- `08-error-boundary-500.png` — unrecoverable error with correlation ID.

Captured via `page.screenshot()` on first run + checked-in. Future visual regressions surface as PNG diffs.

**Alternatives considered**:
- **Replace the mock-fastapi.mjs pattern with a real Python backend in CI**: poetry path is fragile per gotcha #18; mock pattern is what slice 4 + 5 already validated.
- **Skip visual baselines in W1**: defeats the visual-regression purpose of the skeleton.

**Rationale**: extend, don't replace; the dual-server pattern is what makes Playwright tests independent of backend state. W1 adds 4 specs + 4 baselines + reuses the mock.

### D9. Lighthouse a11y bump 0.90 → 0.95 + URL list extension (slice 5 design Q2 deferred answer)

**Decision**: `lighthouserc.cjs` (root, slice 5) has its `assertions.categories.accessibility` bumped from `["error", { minScore: 0.9 }]` to `["error", { minScore: 0.95 }]`. The URLs list is extended to include authenticated-shell stubs:

```js
url: [
  'http://localhost:5173/login',          // existing slice 4-5
  'http://localhost:5173/',               // new W1 — home (portfolio default)
  'http://localhost:5173/research',        // new W1 — domain stubs
  'http://localhost:5173/trades',
  // ... (8 stub URLs)
]
```

Authenticated-shell URLs require a logged-in session; the lhci step in CI sets the cookie via the mock-fastapi pattern (post `/api/v1/auth/login` first, then run lhci with `--collect.headers='Cookie: <session>=<value>'`). Implementation tracked under tasks 7.x.

**Performance score stays informational** (perf < 90 doesn't fail the workflow) — dev-mode Lighthouse penalises non-minified bundles + source maps; switching to `pnpm preview` for prod-build perf is a separate follow-up, deferred per slice 5 D7 trade-off.

**Alternatives considered**:
- **Keep a11y at 0.90**: deferred slice 5 Q2 specifically said "raise to 0.95 once dashboard skeleton lands"; W1 is that moment.
- **Bump perf assertion too**: dev-mode perf is artificially low; prod-build switch is a separate concern (D9 trade-off).
- **Run lhci against `pnpm preview` (prod build)**: requires backend reachable for full auth flow — heavier than the mock pattern. Deferred.

**Rationale**: the bump is the slice contract; perf stays informational because the dev-mode constraint hasn't changed. W1's surface is enough to assert tighter a11y.

### D10. OKLCH design tokens via Tailwind 4.x native + dark-only at MVP, light derivation deferred

**Decision**: `apps/web/postcss.config.cjs` + `apps/web/src/app.css` plant the locked OKLCH tokens from `docs/ux/components.md` §0.3 + `docs/ux/DESIGN.md` §1. Tailwind 4.x is configured native via `@tailwindcss/vite` plugin (no `tailwind.config.ts` — Tailwind 4.x uses CSS imports + native cascade variables). The token set is dark-first; the `<html data-theme="dark">` attr is hard-coded for MVP — the `theme` store reads `prefers-color-scheme` + persists to `localStorage` but only applies `dark` (light variant CSS vars are not declared in this slice; deferred follow-up).

**Token export shape** (in `app.css`):

```css
:root[data-theme='dark'] {
  --bg: oklch(18% 0.02 250);
  --surface: oklch(22% 0.02 250);
  --ink: oklch(95% 0.005 250);
  --accent: oklch(72% 0.14 195);
  --destructive: oklch(64% 0.20 25);
  --success: oklch(72% 0.16 145);
  /* ... full set per components.md §0.3 */
}
```

Tailwind utilities reference tokens via `bg-[var(--bg)]` etc.; component-level styles use the tokens directly.

**Alternatives considered**:
- **Skip Tailwind entirely**: slice 4's login uses inline styles; doesn't scale to 8 domain pages + reusable components.
- **Tailwind 3.x with config file**: Tailwind 4.x is the project canonical (per architecture-decisions.md §Frontend stack rationale + components.md §0); 4.x is buildless-friendly + native OKLCH support.
- **Light + dark tokens in this slice**: light derivation is a non-trivial re-tonification (every token needs an OKLCH inverse); locked spec says dark-first MVP, light-mode toggle UI is a deferred non-blocker.

**Rationale**: Tailwind 4.x is the project canonical; OKLCH tokens are locked in components.md §0.3; dark-only is the MVP contract per components.md §0.3. Documented in `docs/gotchas.md`.

## Risks / Trade-offs

- **[Risk] `import.meta.glob` runtime behaviour in SvelteKit dev vs build vs SSR** → glob resolution in dev mode (Vite HMR) may differ from build mode (static analysis). **Mitigation**: integration test in Playwright (`tests-e2e/sidebar-dynamic.spec.ts`) exercises both modes (dev via webServer; build via a separate spec that runs `pnpm build && pnpm preview` if needed). Also: the `eager: true` flag forces synchronous resolution → fewer surprise async edges. Documented in gotchas.

- **[Risk] `packages/shared-types/src/index.ts` is a placeholder until typegen bot runs** → `+error.svelte` import of `components['schemas']['Problem']` resolves to `unknown`, causing svelte-check to type-error. **Mitigation**: D3 ships a defensive local fallback in `apps/web/src/lib/types/problem.ts` that matches slice 5's Problem schema field-for-field; the import structure stays stable across the placeholder + post-typegen states. Once the typegen bot lands real types, the local fallback is a no-op alias (TypeScript structural compatibility).

- **[Risk] SSE backoff conflicts with backend HeartbeatMixin reconnect timing** → frontend retries `[3, 6, 12, 24, 48]` while backend reconnects on its own cadence; double-reconnect storms possible. **Mitigation**: the contract is explicit — frontend reconnect ONLY runs when `EventSource` emits `error` (connection drop); backend HeartbeatMixin runs server-side independently. The two layers don't race because the frontend's `EventSource` is a passive subscriber. Documented in gotchas.

- **[Risk] Tailwind 4.x is recent (Oct 2024); ecosystem maturity** → svelte-check + Vite 5.4 + SvelteKit 2.8 stack is on the leading edge. **Mitigation**: `@tailwindcss/vite` is the official plugin; pinned to `^4.0` (caret allows minor); fallback is to pin to the exact 4.0.x version that test-passes. If breakage emerges, the rollback is downgrading to Tailwind 3.4 + a config file (one-line revert via `package.json`).

- **[Risk] Lighthouse a11y bump 0.90 → 0.95 fails the workflow on first run** → some authenticated-shell stubs may have implicit a11y violations (sidebar nav role, theme toggle label, etc.) that 0.90 absorbed. **Mitigation**: tasks.md group 7 includes a "fix any a11y findings to clear ≥ 0.95" task; ConnectionIndicator + ThemeToggle + Sidebar each have explicit `aria-*` attrs documented in components.md §2. Worst case: revert the bump to 0.90 + log a follow-up — but the spec scenarios assert ≥ 0.95.

- **[Risk] Visual baseline PNG diffs are noisy across OS / browser engine / font rendering** → checked-in baselines may break in CI vs local. **Mitigation**: Playwright's screenshot comparison has `threshold` config; W1 sets a moderate threshold (0.2 default) so font hinting drift doesn't fail the spec. The baselines are captured in CI on first run (workflow-bot pattern, like slice 5's typegen) so the canonical baseline matches CI's rendering env.

- **[Trade-off] D7 ships 8 stubs in W1 instead of letting each Wave 3-4 slice ship its own** → W1 owns 8 file creations that future slices will replace. **Why this is right**: the alternative is each Wave 3-4 slice creates the file when it implements content, but the sidebar enum test in W1 needs 8 routes to assert against. Without the 8 stubs, the dynamic enumeration is unverified at slice-W1 archive time. The future replacements are body-only swaps — `meta` export stays.

- **[Trade-off] Light-mode UI deferred** → components.md §0.3 says "Tailwind dark mode + system preference desde MVP — *availability* MVP, *toggle UI* W1". This slice ships the `theme` store + system preference reader but NOT the light variant CSS vars + toggle UI. Documented as a deferred follow-up in tasks.md + gotchas. The contract is preserved (theme attribute exists, `prefers-color-scheme` is read) — only the user-facing toggle is missing.

- **[Trade-off] No KillSwitchButton in this slice** → top bar reserves a slot but does not render the button (K1 owns the implementation + the `/api/v1/risk/halt` endpoint). The slot is named (`<TopBar><KillSwitchSlot /></TopBar>`) so K1's PR adds a single component import without TopBar churn. Aligned with anti-collision discipline.

## Migration Plan

This slice has no live deployment to migrate from. Deployment path:

1. Merge slice W1 to main. Wave 2 backend slices (R1, T1, K1, P1, O1) merge in parallel; their PRs do not touch `apps/web/`, no merge conflicts.
2. Wave 3-4 slices that touch UI (R5, R6, T4, K1's frontend, O1's frontend, P1's frontend, O2's frontend) consume the W1 contract:
   - Replace the body of `(app)/<their-domain>/+page.svelte` with real content. `meta` export stays.
   - Add their concrete SSE backend route under `apps/api/src/iguanatrader/api/sse/<name>.py`. The matching `lib/sse/<name>.ts` consumer wrapper is already in place from W1.
   - Use `useFetch` + `useSSE` composables from W1; do NOT add a competing fetch helper.
3. K1 specifically: drops `apps/web/src/lib/components/KillSwitchButton.svelte` + imports it into `TopBar.svelte`'s slot. No TopBar edits beyond the import — the slot is pre-named.
4. T4 specifically: replaces `(app)/portfolio/+page.svelte` body with the J1 dashboard summary; replaces `(app)/trades/+page.svelte` body with the J1 trade history; replaces `(app)/strategies/+page.svelte` body with strategy management.

Rollback = revert PR. The SvelteKit shell is purely additive; the slice 4 (auth) routes + `(app)/portfolio` placeholder are preserved (reverting just removes the new routes + Sidebar + stores — slice 4's auth flow keeps working). No schema changes, no destructive operations.

## Open Questions

- **Q**: Should the `meta` export per route be a Zod-validated runtime contract (warn on shape mismatch) or just a TypeScript type (compile-time only)? **Tentative answer**: TypeScript type only (zero runtime cost; `as const` enforces literal types; svelte-check catches mismatches at build). Add Zod if a Wave 3-4 slice ships a malformed meta that escapes review.

- **Q**: Should `useFetch` retry idempotent requests on transient 5xx (network blip)? **Tentative answer**: NO in this slice — retries are caller-side (each domain page decides). `useFetch` is a thin wrapper; retry logic is a Wave 3-4 concern when concrete pages need it. Document in gotchas + revisit if pattern emerges.

- **Q**: SSE backoff frontend mirror exact-match vs frontend-specific cadence? **Tentative answer**: exact-match `[3, 6, 12, 24, 48]` (slice 2 canonical). Documented in components.md + gotchas. If frontend-specific tuning emerges, it's a follow-up, NOT a slice-W1 deviation.

- **Q**: Should the connection indicator be a single global aggregate or per-stream visible? **Tentative answer**: single global ("Live" / "Reconnecting" / "Disconnected") in the top bar, per-stream detail surfaces only on hover (tooltip). Per components.md §2 + j1.md §3 step 1.

- **Q**: Light-mode CSS vars in this slice or deferred? **Tentative answer**: deferred (per D10 + scope discipline). The `theme` store reads system preference; the CSS only declares `dark` variant; light is a follow-up slice.
