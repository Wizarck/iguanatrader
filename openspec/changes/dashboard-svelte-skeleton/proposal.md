## Why

Slice 4 (`auth-jwt-cookie`) shipped the SvelteKit scaffold + `(auth)/login` + `(app)/+layout.{server.ts,svelte}` + `hooks.server.ts` cookie gate + a single placeholder `(app)/portfolio/+page.svelte`. Slice 5 (`api-foundation-rfc7807`) shipped `packages/shared-types` with the regenerated `Problem` type, the `/api/v1/stream/*` SSE prefix, and the dynamic-discovery contract on the backend. Wave 2 now needs the **frontend twin of slice 5's anti-collision pattern**: a dashboard skeleton where each downstream slice (R5 research, T4 trades/portfolio/strategies, P1 approvals, K1 risk, O1 costs, R6 settings) drops a `(app)/<name>/+page.svelte` and the navigation surface picks it up automatically — with no edits to a shared `Sidebar.svelte` or registry file. Without this, every Wave 3-4 slice that touches the UI races on the sidebar nav array. This change plants the **frontend anti-collision foundation**: `Sidebar.svelte` enumerates routes via `import.meta.glob('/src/routes/(app)/*/+page.svelte')`, the `(app)` layout group becomes the canonical authenticated shell (sidebar + top bar + connection indicator + content slot), `+error.svelte` renders the RFC 7807 `Problem` typed via `@iguanatrader/shared-types`, base stores + composables (`useFetch`, `useSSE`) standardize backend access with credentials + reconnect, and 8 domain pages render `"loading…"` placeholders so future slices only swap content. Now is the right time because Wave 2 has 5 backend slices in flight (R1, T1, K1, P1, O1); their frontend consumers must wait until W1 lands the shell or duplicate scaffolding.

## What Changes

- **(app) layout group authenticated shell** — extend the existing minimal `apps/web/src/routes/(app)/+layout.svelte` (slice 4 stub) with Sidebar + top bar + main content region + ConnectionIndicator strip. The cookie hook in `hooks.server.ts` already gates the route group (slice 4 contract); this slice consumes it as-is + reads `event.locals.user` via the existing `+layout.server.ts` load.
- **Dynamic Sidebar.svelte (anti-collision)** — `apps/web/src/lib/components/nav/Sidebar.svelte` enumerates routes at compile time via `import.meta.glob('/src/routes/(app)/*/+page.svelte', { eager: true })`. Each route module MAY export a `meta: { label, icon, order, requiresRole? }` const; routes without it fall back to a kebab-cased path label + default icon + order=100. Sorted alphabetically by `order` then `href`. Each Wave 3-4 slice adds its own `(app)/<name>/+page.svelte` with `meta` and the sidebar updates with zero edits to `Sidebar.svelte`.
- **+error.svelte global boundary** — `apps/web/src/routes/+error.svelte` renders the RFC 7807 `Problem` body from `$page.error`, typed via `import type { components } from '@iguanatrader/shared-types'` (consuming slice 5's `Problem` schema component). Recoverable (4xx with hint) vs unrecoverable (5xx with correlation ID + copy button) variants per `docs/ux/components.md` §2.3.
- **Base stores** — `apps/web/src/lib/stores/{auth,nav,theme,connection}.ts`: `auth` mirrors `event.locals.user`; `nav` tracks sidebar collapsed/expanded + active href; `theme` reads `prefers-color-scheme` + `localStorage` toggle; `connection` aggregates SSE health (per-stream + global).
- **Base composables** — `apps/web/src/lib/composables/{useFetch,useSSE}.ts`: `useFetch` wraps native `fetch` with `credentials: 'include'` + RFC 7807 error parse (returns typed `Problem` on 4xx/5xx); `useSSE` wraps `EventSource` with reconnect-on-drop using slice 2's canonical backoff `[3, 6, 12, 24, 48]` seconds + connection store integration.
- **SSE consumer stubs** — `apps/web/src/lib/sse/{research,trades,costs,risk,approvals,equity,alerts}.ts` thin wrappers over `useSSE` pointing at `/api/v1/stream/<name>` (mounts declared by slice 5). They are stubs (return null payloads) until each Wave 3-4 backend slice ships its concrete SSE route; the wiring + reconnect contract is in place from W1.
- **Domain page stubs (8)** — `apps/web/src/routes/(app)/{research,trades,strategies,settings,costs,risk,approvals}/+page.svelte` each render `"loading…"` placeholder with `meta` export so Sidebar enumerates them. The existing `(app)/portfolio/+page.svelte` (slice 4 placeholder) is updated to match the same pattern + `meta` export. Each future slice (T4, K1, O1, P1, R5, R6) replaces the body, never touches the sidebar.
- **Tailwind 4.x + OKLCH design tokens** — root `apps/web/postcss.config.cjs` + `apps/web/src/app.css` plant the OKLCH tokens locked in `docs/ux/components.md` §0.3 + `docs/ux/DESIGN.md` §1 (dark-first, light derivation deferred per components.md §0.3). Tailwind 4.x is configured native via `@tailwindcss/vite` plugin.
- **Lighthouse CI a11y bump 90 → 95** — update `lighthouserc.cjs` (slice 5) so a11y minScore is `0.95` and append the new `(app)` URLs (`/`, `/portfolio`, `/research`, `/trades`, etc. — drives lhci against authenticated-shell stubs as well as `/login`). Per slice 5 D7 + design Q2: dashboard skeleton justifies the bump.
- **Playwright e2e + visual baselines** — extend slice 4's dual-server `playwright.config.ts` (mock-fastapi + SvelteKit dev) with new specs: `tests-e2e/dashboard-skeleton.spec.ts` (authenticated shell renders sidebar with all 8 domain links, +error.svelte renders Problem, theme toggle persists), `tests-e2e/sidebar-dynamic.spec.ts` (drop a stub route at fixture time → assert it appears in sidebar). Visual baselines under `tests-e2e/screenshots/` for sidebar (collapsed + expanded), domain stubs, error states, theme toggle.
- **Out of scope**: concrete content for any of the 8 domain pages (each Wave 3-4 slice plants its own); concrete SSE backends (slice 5 declared the prefix; the 5 Wave 2 backend slices declare per-context routers; this slice consumes mounts that already exist + stubs the rest); Storybook + per-component visual catalogue (deferred to a later UX slice — components.md §1 stories listed but not built); RBAC enforcement on Sidebar items (slice T4 + role-aware backend); KillSwitchButton in the top bar (slice K1 owns the button + endpoint; W1 just leaves the slot in the layout).

## Capabilities

### New Capabilities

- `web-dashboard`: SvelteKit `(app)` authenticated shell — dynamic Sidebar via `import.meta.glob` (anti-collision), `+error.svelte` rendering RFC 7807 typed Problems, base stores (auth, nav, theme, connection), base composables (useFetch with credentials, useSSE with backoff reconnect), 7 SSE consumer stubs aligned with slice 5's mount, 8 domain page stubs rendering `"loading…"` placeholder, Tailwind 4.x + OKLCH design tokens, Lighthouse CI a11y ≥ 95 + Playwright e2e + visual baselines.

### Modified Capabilities

(none — slice 4's `web-authentication` spec is unchanged at the requirement level. The cookie hook is consumed as-is; the `(auth)/login` flow keeps its current contract; the `(app)/+layout.{server.ts,svelte}` files extend rather than replace.)

## Impact

- **Affected code (W1-owned, write-allowed)**:
  - `apps/web/src/routes/(app)/+layout.svelte` (MOD) — extend to render Sidebar + top bar + content slot (currently a one-line `{@render children()}`).
  - `apps/web/src/routes/+error.svelte` (NEW) — global error boundary rendering Problem.
  - `apps/web/src/routes/(app)/{research,trades,strategies,settings,costs,risk,approvals}/+page.svelte` (NEW × 7) — domain stubs.
  - `apps/web/src/routes/(app)/portfolio/+page.svelte` (MOD) — slice 4's placeholder updated to match the stub pattern + add `meta` export.
  - `apps/web/src/lib/components/nav/Sidebar.svelte` (NEW) — dynamic enumeration via `import.meta.glob`.
  - `apps/web/src/lib/components/nav/{TopBar,ConnectionIndicator}.svelte` (NEW) — top bar with theme toggle + connection strip.
  - `apps/web/src/lib/stores/{auth,nav,theme,connection}.ts` (NEW × 4).
  - `apps/web/src/lib/composables/{useFetch,useSSE}.ts` (NEW × 2).
  - `apps/web/src/lib/sse/{research,trades,costs,risk,approvals,equity,alerts}.ts` (NEW × 7).
  - `apps/web/src/app.css` (NEW) + `apps/web/postcss.config.cjs` (NEW) + `apps/web/src/app.html` (MOD; load `app.css` + theme attr).
  - `apps/web/package.json` (MOD) — add `tailwindcss@^4.0`, `@tailwindcss/vite`, `lucide-svelte` (per components.md §0.5).
  - `apps/web/playwright.config.ts` (MOD) — add new spec files via testMatch.
  - `apps/web/tests-e2e/{dashboard-skeleton,sidebar-dynamic,error-boundary,theme-toggle}.spec.ts` (NEW × 4) + `tests-e2e/screenshots/` baselines.
  - `lighthouserc.cjs` (MOD; slice 5 root) — bump a11y minScore to 0.95 + append authenticated-shell URLs.
  - `docs/gotchas.md` (MOD) — gotcha entries for SvelteKit `import.meta.glob` runes-mode caveats + Tailwind 4.x + Playwright dual-server SSE quirks (if any surface during scenarios).
- **Affected code (slice 4/5-owned, read-only consumed)**:
  - `apps/web/src/hooks.server.ts` (slice 4) — consumed unchanged; it already redirects unauth to `/login?redirect_to=...`.
  - `apps/web/src/routes/(app)/+layout.server.ts` (slice 4) — consumed unchanged; W1 reads `data.user` from page data.
  - `apps/web/src/routes/(auth)/login/+page.svelte` (slice 4) — kept-as-is per scope; ungated, dark themed via the new global tokens.
  - `apps/web/src/lib/{config,redirect}.ts` (slice 4) — `useFetch` reuses `API_BASE_URL`.
  - `packages/shared-types/src/index.ts` (slice 5) — typegen artefact; W1 imports `components['schemas']['Problem']` for `+error.svelte` and Problem-shaped error returns from `useFetch`. Note: the file is currently a placeholder (`export {};`) per slice 5 archive task 4.3; CI typegen bot regenerates it on the next backend push that touches DTOs. W1 imports defensively via `type-only` imports + a local fallback type so svelte-check stays green even pre-regeneration.
- **Affected APIs**: none (frontend-only). The `useFetch` + `useSSE` composables only consume `/api/v1/*` and `/api/v1/stream/*` declared by slices 4 + 5; W1 mounts no new endpoints.
- **Affected dependencies**:
  - `tailwindcss@^4.0` + `@tailwindcss/vite@^4.0` — runtime + build (Tailwind 4.x native OKLCH per components.md §0.3).
  - `lucide-svelte@^0.460` — icon library locked in components.md §0.5.
  - `@playwright/test` — already present (slice 4); W1 reuses.
  - `@lhci/cli` — already present (slice 5); W1 only edits the rc file.
- **Prerequisites**:
  - `auth-jwt-cookie` (slice 4) — provides `(auth)/login`, `hooks.server.ts` cookie gate, `(app)/+layout.{server.ts,svelte}` stub, and `tests-e2e/mock-fastapi.mjs` Playwright mock pattern that W1 extends.
  - `api-foundation-rfc7807` (slice 5) — provides `packages/shared-types` (Problem schema), the `/api/v1/stream/*` SSE prefix, and the `lighthouserc.cjs` baseline this slice modifies.
- **Capability coverage** (per `docs/openspec-slice.md` row W1): FR54 (real-time portfolio + equity + approvals + costs + risk surface — skeleton planted, content per Wave 3-4 slices), FR55 (kill-switch surface — top bar slot reserved; K1 wires the button), NFR-P7 (dashboard page load <500ms localhost — Lighthouse perf tracked informationally; a11y is the hard threshold).
- **Out of scope** (per slice scope row + design discipline):
  - Concrete domain page content for any of research / trades / portfolio / strategies / settings / costs / risk / approvals.
  - KillSwitchButton component implementation (K1).
  - Approval flow / proposal cards / brief renderers / weekly review PDF (P1, R5, O2).
  - Backend changes of any kind (`apps/api/`, `packages/shared-types/` typegen output, `apps/openbb-sidecar/`).
  - Storybook + per-component visual catalogue.
  - RBAC enforcement on Sidebar items (T4 + role-aware backend).
  - Light-mode toggle UI (mentioned in components.md §0.3 as a slice W1 deliverable, but the locked tokens are dark-first only — light derivation deferred to a follow-up; this slice ships the `theme` store + system-preference reader + a `data-theme="dark"` attr only).
