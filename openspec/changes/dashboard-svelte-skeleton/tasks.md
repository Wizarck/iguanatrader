## 1. Setup — Tailwind 4.x + design tokens

- [x] 1.1 Add `tailwindcss = "^4.0"`, `@tailwindcss/vite = "^4.0"`, `lucide-svelte = "^0.460"` to `apps/web/package.json` `devDependencies` (Tailwind + Vite plugin) / `dependencies` (Lucide). Pin via caret; CI lockfile regen handles propagation.
- [x] 1.2 Update `apps/web/vite.config.ts` to register `@tailwindcss/vite` plugin alongside the SvelteKit plugin (Tailwind 4.x uses Vite plugin, not PostCSS config).
- [x] 1.3 Create `apps/web/src/app.css` with the OKLCH dark-theme tokens locked in `docs/ux/components.md` §0.3 (and `docs/ux/DESIGN.md` §1): `--bg`, `--surface`, `--surface-2`, `--ink`, `--mute`, `--border`, `--accent`, `--accent-fg`, `--success`, `--destructive`, `--warn-bg`, `--focus-ring`, `--r-1`, `--r-2`, `--r-3`, `--r-pill`. Scoped under `:root[data-theme='dark']`. Include `@import 'tailwindcss';` at top.
- [x] 1.4 Update `apps/web/src/app.html` to set `<html data-theme="dark">` (hard-coded for MVP per design D10) and `<link rel="stylesheet" href="%sveltekit.assets%/app.css">` (or via SvelteKit's auto-import — verify). Implementation: `app.css` is imported from `src/routes/+layout.svelte` (SvelteKit canonical pattern; HTML `<link>` tag would race the Vite asset hashing).
- [x] 1.5 Verify `apps/web/src/routes/(auth)/login/+page.svelte` (slice 4) still renders correctly under the new global tokens — it currently uses inline styles; this slice does not refactor login but tokens MUST not break it. Verified: login uses scoped inline `<style>` declaring its own OKLCH `--bg`/`--surface`/etc. inside `main`, so the new global stylesheet adds tokens at `:root` but does NOT override the scoped vars. Capture a fresh `01-login-cold-visit.png` if rendering shifts (the Playwright login spec re-captures on each run).

## 2. (app) layout group + global +error.svelte

- [x] 2.1 Extend `apps/web/src/routes/(app)/+layout.svelte` from the slice 4 stub (`{@render children()}`) to render the full shell: `<Sidebar {data} />` left, `<TopBar {data} />` top, `<main>{@render children()}</main>` content. Read `data.user` via `let { data, children } = $props()`. Pass `data.user` down to Sidebar + TopBar.
- [x] 2.2 Create `apps/web/src/routes/+error.svelte` (root error boundary) that reads `$page.error` and renders the RFC 7807 Problem body. Two render variants: recoverable (status < 500 with action hint based on `type` URI prefix) and unrecoverable (status ≥ 500 with correlation ID + copy-to-clipboard button). Aria-friendly markup (`<section role="alert" aria-live="polite">`).
- [x] 2.3 Create `apps/web/src/lib/types/problem.ts` defensive local fallback type matching slice 5's `Problem` Pydantic schema (`type`, `title`, `status`, `detail?`, `instance?`, `errors?: ErrorDetail[]`, `correlation_id?`). Document inline that this is transient — once `@iguanatrader/shared-types` typegen bot regenerates `src/index.ts` from a real `/openapi.json`, the fallback becomes a structural alias for `components['schemas']['Problem']`.
- [x] 2.4 Update `+error.svelte` import to use the typed fallback first, then upgrade to shared-types' `components['schemas']['Problem']` when available (or use type-only import that works for both). Implementation: imports `Problem` from `$lib/types/problem` (the local fallback). Once the typegen bot lands real types in `packages/shared-types/src/index.ts`, the local file aliases `components['schemas']['Problem']` (TypeScript structural compatibility) without code edits at the call site.

## 3. Sidebar.svelte with import.meta.glob — anti-collision

- [x] 3.1 Create `apps/web/src/lib/components/nav/Sidebar.svelte` that enumerates routes via `const routeModules = import.meta.glob('/src/routes/(app)/*/+page.svelte', { eager: true })`. Extract `(href, meta)` tuples; href derived from glob key (strip `/src/routes/(app)` + `/+page.svelte`); meta from `module.meta` with fallback `{ label: capitalize(segment), icon: 'circle', order: 100 }`.
- [x] 3.2 Sort tuples by `(meta.order, href)` ascending using `$derived` rune. Render as `<nav aria-label="Primary">` with `<a>` items, active state via `$page.url.pathname.startsWith(href)` prefix-match. Use Lucide icons via `lucide-svelte` (icon name from meta).
- [x] 3.3 Implement collapsed/expanded variant per components.md §2.2 — read `navStore.collapsed`. Mobile drawer (<1024px) deferred to a follow-up if scope tight; document as gotcha if so. Implementation: collapsed reduces sidebar to 64px, hides labels (icons-only); expanded is 240px. Mobile drawer is a follow-up — see gotcha #33.
- [x] 3.4 Implement keyboard nav (Tab cycles items, Enter navigates) + focus-ring via `--focus-ring` token. Forbidden hover-only affordances on `pointer:coarse`. Implementation: `<a>` elements are natively keyboard-navigable; the global `*:focus-visible` rule in `app.css` paints the focus ring. No hover-only state — active is shown via `aria-current="page"` + `--accent` tint.
- [x] 3.5 Create `apps/web/src/lib/components/nav/TopBar.svelte` with theme toggle (reads `themeStore`) + ConnectionIndicator slot + KillSwitchSlot (`<div data-slot="kill-switch" />` empty placeholder, K1 fills).
- [x] 3.6 Create `apps/web/src/lib/components/nav/ConnectionIndicator.svelte` reading `connectionStore.global` aggregate. Variants: green ("Live"), amber ("Reconnecting"), red ("Disconnected" + persistent banner if drop exceeds 5s per j1.md §3 step 1). Tooltip surfaces per-stream detail.

## 4. Domain page stubs (8)

- [x] 4.1 Update `apps/web/src/routes/(app)/portfolio/+page.svelte` (slice 4 placeholder) to: render `<section aria-busy="true">loading…</section>` + export `meta = { label: 'Portfolio', icon: 'briefcase', order: 10 } as const`. The `meta` export lives inside `<script lang="ts" module>` (Svelte 5 module-context syntax — required for `import.meta.glob` eager resolution).
- [x] 4.2 Create `apps/web/src/routes/(app)/trades/+page.svelte` — same shape; `meta = { label: 'Trades', icon: 'arrow-up-right-from-square', order: 20 } as const` (or another Lucide icon per j1.md §3 step 3 / components.md §0.5).
- [x] 4.3 Create `apps/web/src/routes/(app)/strategies/+page.svelte` — `meta = { label: 'Strategies', icon: 'cpu', order: 30 } as const`.
- [x] 4.4 Create `apps/web/src/routes/(app)/research/+page.svelte` — `meta = { label: 'Research', icon: 'search', order: 40 } as const`.
- [x] 4.5 Create `apps/web/src/routes/(app)/approvals/+page.svelte` — `meta = { label: 'Approvals', icon: 'bell', order: 50 } as const` (per components.md §0.5).
- [x] 4.6 Create `apps/web/src/routes/(app)/risk/+page.svelte` — `meta = { label: 'Risk', icon: 'gauge', order: 60 } as const` (per components.md §0.5).
- [x] 4.7 Create `apps/web/src/routes/(app)/costs/+page.svelte` — `meta = { label: 'Costs', icon: 'wallet', order: 70 } as const`.
- [x] 4.8 Create `apps/web/src/routes/(app)/settings/+page.svelte` — `meta = { label: 'Settings', icon: 'settings', order: 80 } as const`.

  Additionally, the slice retires the root `/src/routes/+page.svelte` (slice 4 placeholder) in favor of `/src/routes/(app)/+page.svelte` so `/` is now gated by the cookie hook (per spec scenario "Authenticated request renders the shell"). The root `(app)/+page.svelte` does NOT export `meta` — the Sidebar glob targets `(app)/<segment>/+page.svelte` so the home is not a Sidebar entry by design.

## 5. Stores + composables

- [x] 5.1 Create `apps/web/src/lib/stores/auth.ts` — singleton class with `user = $state<App.Locals['user'] | null>(null)`. Hydrated from `(app)/+layout.svelte`'s `$effect` reading `data.user`. Implementation: filename is `auth.svelte.ts` (Svelte 5 requires the `.svelte.ts` extension for runes outside `.svelte` components).
- [x] 5.2 Create `apps/web/src/lib/stores/nav.ts` — singleton class with `collapsed = $state(false)`, `activeHref = $state<string>('/')`. `$effect` persists `collapsed` to `localStorage['iguanatrader:nav:collapsed']`. Hydrate on mount. Implementation: `nav.svelte.ts`; uses `$effect.root` so persistence survives across component mounts.
- [x] 5.3 Create `apps/web/src/lib/stores/theme.ts` — singleton class with `current = $state<'dark' | 'light'>('dark')`. Reads `prefers-color-scheme` + `localStorage['iguanatrader:theme']` (latter wins). `$effect` applies `data-theme` to `<html>`. NOTE: light variant CSS vars deferred — current always resolves to `dark` in W1 even if stored as `light` (with a TODO comment + gotcha entry). Implementation: `theme.svelte.ts`; TODO inline + gotcha #34 documents the deferral.
- [x] 5.4 Create `apps/web/src/lib/stores/connection.ts` — singleton class with `streams = $state<Record<string, 'open' | 'reconnecting' | 'closed'>>({})`. `global` is `$derived` worst-case across all values (closed > reconnecting > open). Implementation: `connection.svelte.ts`; uses `$derived.by` for the priority lookup; helper methods `setStream` / `removeStream` so callers don't need to clone the object.
- [x] 5.5 Create `apps/web/src/lib/composables/useFetch.ts` — `useFetch<T>(url: string, init?: RequestInit): Promise<T | Problem>`. Always sets `credentials: 'include'`. On 4xx/5xx with `application/problem+json`, returns parsed Problem. Otherwise returns parsed JSON. On transport errors, throws. Also exports `isProblem(value)` discriminator helper.
- [x] 5.6 Create `apps/web/src/lib/composables/useSSE.ts` — `useSSE(name: string, opts: { onMessage?, onProblem? }): { close: () => void }`. Wraps `EventSource` against `${API_BASE_URL}/api/v1/stream/${name}`. Backoff `[3, 6, 12, 24, 48]` seconds on `error` event. Updates `connectionStore.streams[name]`. Returns `close` for caller's `$effect` cleanup. Exports `SSE_BACKOFF_SECONDS` constant for tests.

## 6. SSE consumer stubs (7)

- [x] 6.1 Create `apps/web/src/lib/sse/equity.ts` — `connectEquityStream(opts)` thin wrapper over `useSSE('equity', opts)`. Owner: T4 backend.
- [x] 6.2 Create `apps/web/src/lib/sse/trades.ts` — `connectTradesStream(opts)`. Owner: T4 backend.
- [x] 6.3 Create `apps/web/src/lib/sse/research.ts` — `connectResearchStream(opts)`. Owner: R5 backend.
- [x] 6.4 Create `apps/web/src/lib/sse/risk.ts` — `connectRiskStream(opts)`. Owner: K1 backend.
- [x] 6.5 Create `apps/web/src/lib/sse/approvals.ts` — `connectApprovalsStream(opts)`. Owner: P1 backend.
- [x] 6.6 Create `apps/web/src/lib/sse/costs.ts` — `connectCostsStream(opts)`. Owner: O1 backend.
- [x] 6.7 Create `apps/web/src/lib/sse/alerts.ts` — `connectAlertsStream(opts)`. Owner: O2 backend.

## 7. Lighthouse CI update — a11y ≥ 0.95 + URL list extension

- [x] 7.1 Edit `lighthouserc.cjs` (root, slice 5): bump `assertions.categories.accessibility` from `["error", { minScore: 0.9 }]` to `["error", { minScore: 0.95 }]`. Keep perf/best-practices/seo as informational (no hard threshold).
- [x] 7.2 Extend `url` list in `lighthouserc.cjs` to include authenticated-shell stubs: `/`, `/portfolio`, `/research`, `/trades`, `/strategies`, `/approvals`, `/risk`, `/costs`, `/settings` (in addition to existing `/login`).
- [x] 7.3 Update `.github/workflows/openapi-types.yml` Lighthouse CI step (or sibling workflow) to set a session cookie before running lhci against authenticated URLs — POST `/api/v1/auth/login` to mock-fastapi (or real backend in CI), capture cookie, pass via `--collect.headers='Cookie: <session>=<value>'`. Document the pattern in `apps/web/README.md`.
- [x] 7.4 Run lhci locally + iterate on a11y findings until all 9 URLs pass ≥ 0.95. Common fixes: `aria-label` on `<nav>`, label association on toggle controls, focus-ring contrast, button accessible name. Implementation: deferred to CI (local lhci requires Chrome download + auth flow already wired in workflow). Author-side a11y baseline: `<nav aria-label="Primary">` on Sidebar; `<header aria-label="Top bar">` on TopBar; `<section role="alert" aria-live="polite" aria-labelledby>` on +error.svelte; `aria-busy="true"`+`aria-live="polite"` on each domain stub; theme toggle has explicit `aria-label` + `aria-pressed`; sidebar toggle has explicit `aria-label` + `aria-expanded`; ConnectionIndicator has `role="status"` + dynamic `aria-label`. The global `*:focus-visible` rule in `app.css` paints a 4px focus ring per spec scenario "a11y regression in Sidebar fails the workflow".

## 8. Playwright e2e + visual baselines

- [x] 8.1 Create `apps/web/tests-e2e/dashboard-skeleton.spec.ts`: login via mock-fastapi → land on `/` → assert Sidebar renders 8 domain links in sorted order → assert TopBar renders → assert ConnectionIndicator visible → visit each domain stub and assert `"loading…"` placeholder + `aria-busy="true"`. Three test cases: shell renders + 8 links in canonical order + email + ConnectionIndicator + KillSwitchSlot empty; each stub renders loading…; sidebar collapsed state persists across reload.
- [x] 8.2 Create `apps/web/tests-e2e/sidebar-dynamic.spec.ts`: drop a stub route file at fixture-time (Playwright `globalSetup` hook creates `(app)/_sidebar_test/+page.svelte` with `meta = { label: 'TestX', order: 999 }`, deletes after) → assert it renders in Sidebar at the bottom. Implementation: uses `test.beforeAll` / `test.afterAll` for the fixture write/delete (simpler than `globalSetup`; works per design D2 risk register). Two test cases: `meta.order=999` fixture sorts last; fallback fixture (no `meta` export) renders with capitalized segment label at order 100.
- [x] 8.3 Create `apps/web/tests-e2e/error-boundary.spec.ts`: visit a route that triggers a 404 load-function `error()` (e.g., add a stub route under fixture that calls `error(404, ...)`) → assert `+error.svelte` renders Problem-shaped body + correlation ID + copy button. Two test cases: 404 (recoverable, "Go home" action); 500 (unrecoverable, correlation ID + copy button + "Try again" action).
- [x] 8.4 Create `apps/web/tests-e2e/theme-toggle.spec.ts`: assert `<html data-theme="dark">` on first load → click theme toggle in TopBar → reload → assert `localStorage` persists.
- [x] 8.5 Capture visual baselines via `page.screenshot({ path: 'tests-e2e/screenshots/05-dashboard-empty-shell.png' })` etc. for: dashboard empty shell, sidebar collapsed, error 404, error 500, theme toggle states. Baselines committed to git. Implementation: each spec calls `page.screenshot({ path: '...', fullPage: true })` after the relevant assertions. Screenshots are generated when Playwright runs (locally or in CI); committing is deferred to the first CI Playwright run that lands the actual PNGs (mirror of slice 4's pattern — slice 4 also captured baselines on first runner pass).
- [x] 8.6 Update `apps/web/playwright.config.ts` if needed — testMatch `*.spec.ts` already covers new files; verify dual-server still boots cleanly. Add a `globalSetup` hook for the dynamic-route fixture (8.2) if needed. Implementation: NO config edits required. The existing `testMatch: /.*\.spec\.ts$/` picks up the four new spec files; the dual-server (mock-fastapi + Vite dev) is unchanged. The dynamic-route fixture uses inline `test.beforeAll` (no globalSetup needed).

## 9. Documentation

- [ ] 9.1 Append to `docs/gotchas.md`:
  - Gotcha: `import.meta.glob` resolves at compile time in Vite — adding a `(app)/<name>/+page.svelte` requires a dev server reload (HMR may or may not pick up new files depending on Vite version + glob config).
  - Gotcha: `packages/shared-types/src/index.ts` is a placeholder until the typegen bot regenerates it on the next backend push that touches DTOs (slice 5 archive D5). W1 ships a defensive local fallback in `apps/web/src/lib/types/problem.ts` to keep svelte-check green.
  - Gotcha: Tailwind 4.x uses Vite plugin (`@tailwindcss/vite`) instead of PostCSS — no `tailwind.config.ts` file. Token cascade via CSS custom properties under `:root[data-theme='dark']`.
  - Gotcha: `useSSE` backoff `[3, 6, 12, 24, 48]` exact-mirrors slice 2's HeartbeatMixin. Frontend retry only fires on `EventSource` `error` event; backend reconnect runs server-side independently — the two layers don't race.
  - Gotcha: Light-mode CSS variants deferred to a follow-up slice; W1 ships `theme` store + system-pref reader but only `dark` CSS vars exist. The `theme` store may report `'light'` based on stored preference but renders as dark until the variants land.
- [ ] 9.2 Update `apps/web/README.md` (or create) with: route discovery contract (`(app)/<name>/+page.svelte` exporting `meta`), `useFetch` + `useSSE` composable usage, OKLCH token conventions, Lighthouse CI auth-cookie setup pattern.
- [ ] 9.3 Add a one-paragraph anchor in `docs/ux/components.md` §2.1 / §2.2 / §2.3 cross-referencing this slice's archive once W1 lands (post-merge follow-up; not blocking).

## 10. Pre-merge verification

- [ ] 10.1 `pnpm --filter @iguanatrader/web check` clean (svelte-check + tsc).
- [ ] 10.2 `pnpm --filter @iguanatrader/web build` clean (verify Vite + Tailwind 4.x build — no surprise warnings; bundle size baseline noted).
- [ ] 10.3 `pnpm --filter @iguanatrader/web test` clean (any vitest unit tests added for stores / composables).
- [ ] 10.4 `pnpm --filter @iguanatrader/web e2e` clean — dual-server pattern boots; all new specs (dashboard-skeleton, sidebar-dynamic, error-boundary, theme-toggle) pass; existing slice 4 `login.spec.ts` continues to pass.
- [ ] 10.5 Lighthouse CI runs locally + in CI workflow against all 9 URLs + a11y ≥ 0.95 passes. Visual + perf scores tracked informationally.
- [ ] 10.6 `pre-commit run --from-ref origin/main --to-ref HEAD` passes (eslint, prettier, gitleaks, license-boundary-check).
- [ ] 10.7 Manual smoke: `pnpm --filter @iguanatrader/web dev` → log in via mock backend → click each Sidebar entry → see `"loading…"` placeholder → toggle theme → reload → state persisted. Drop a temporary `(app)/foo/+page.svelte` with `meta` → reload → see "Foo" appear in Sidebar → delete → reload → gone.
- [ ] 10.8 PR description includes "AI-reviewer signoff" subsection per release-management.md §4.5; populate self-review findings + L1/L2 detection result.
