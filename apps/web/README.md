# `apps/web/` — iguanatrader SvelteKit dashboard

The single-tenant operational dashboard. Slice 4 shipped `(auth)/login`,
slice 5 set up `packages/shared-types` + Lighthouse CI, and slice W1
(this slice) plants the authenticated shell — Sidebar + TopBar +
content + connection indicator + base stores + composables.

## Stack

- **SvelteKit 2.x + Svelte 5** (runes mode).
- **Tailwind 4.x** via the `@tailwindcss/vite` plugin (no
  `tailwind.config.ts`, no `postcss.config.cjs` — see gotcha #72 in
  `docs/gotchas.md`).
- **OKLCH design tokens** in `src/app.css` under `:root[data-theme='dark']`
  (locked in `docs/ux/components.md` §0.3 + `docs/ux/DESIGN.md` §1).
- **Lucide icons** via `lucide-svelte`.
- **Playwright** for e2e + visual baselines.
- **Vitest** for unit tests (currently used for `auth-flow.test.ts`).
- **Lighthouse CI** for a11y gating (≥ 0.95 since W1).

## Local dev

```sh
pnpm install                              # at the repo root
pnpm --filter @iguanatrader/web dev       # vite dev on :5173
```

Default backend URL is `http://127.0.0.1:8000` (real FastAPI). For e2e
runs the `IGUANATRADER_API_BASE_URL` env var points at the
mock-fastapi node script (see Playwright section).

## Anti-collision route discovery contract

`Sidebar.svelte` enumerates routes at build time via:

```ts
const routeModules = import.meta.glob<RouteModule>(
  '/src/routes/(app)/*/+page.svelte',
  { eager: true }
);
```

Every route module under `(app)/<segment>/+page.svelte` MAY export a
top-level `meta` const inside a `<script lang="ts" module>` tag:

```svelte
<script lang="ts" module>
  export const meta = {
    label: 'Portfolio',
    icon: 'briefcase',     // Lucide icon name (see Sidebar.svelte ICON_MAP)
    order: 10,             // sort key, default 100
    requiresRole: 'admin'  // optional; not enforced in W1, T4 wires
  } as const;
</script>
```

Routes without `meta` get a fallback (`label: capitalize(segment)`,
`icon: 'circle'`, `order: 100`). Sidebar entries are sorted by
`(order, href)` ascending; ties break alphabetically.

**The contract is "drop a `(app)/<name>/+page.svelte` exporting `meta`;
the rest is automatic."** Subsequent slices add their own domain
pages under `(app)/<name>/+page.svelte` and the Sidebar picks them up
with **zero edits to `Sidebar.svelte`** — that's the anti-collision
mechanism. See gotcha #70 for HMR caveats.

## Composables

### `useFetch<T>(url, init?)`

`apps/web/src/lib/composables/useFetch.ts`. Always sends
`credentials: 'include'` (cookie hook depends on it). Returns a
parsed Problem (NOT throws) on 4xx/5xx with `application/problem+json`;
throws on transport errors.

```ts
import { useFetch, isProblem } from '$lib/composables/useFetch';

const result = await useFetch<Trade[]>('/api/v1/trades');
if (isProblem(result)) {
  // Render Problem UI: result.title, result.detail, result.correlation_id
} else {
  // result is Trade[].
}
```

### `useSSE(name, opts)`

`apps/web/src/lib/composables/useSSE.ts`. Wraps `EventSource` against
`${API_BASE_URL}/api/v1/stream/<name>` with reconnect-on-drop using
the canonical backoff `[3, 6, 12, 24, 48]` seconds (mirror of slice 2's
`HeartbeatMixin`). Returns `{ close }` — call from `$effect` cleanup.

```ts
import { connectEquityStream } from '$lib/sse/equity';

$effect(() => {
  const handle = connectEquityStream({
    onMessage: (event) => { /* ... */ }
  });
  return () => handle.close();
});
```

7 SSE consumer wrappers live under `src/lib/sse/`: `equity`, `trades`,
`research`, `risk`, `approvals`, `costs`, `alerts` (see W1 design D6
for backend-slice ownership map).

## OKLCH token conventions

All tokens live in `src/app.css` under `:root[data-theme='dark']`.
Reference them in components via either:

```css
.surface {
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--border);
}
```

or via Tailwind utility classes with arbitrary values:

```html
<div class="bg-[var(--surface)] text-[var(--ink)]">…</div>
```

Token cheat-sheet (see `docs/ux/components.md` §0.3 for the full set):

| Token | Purpose |
|---|---|
| `--bg` | App-level background |
| `--surface` | Card / panel background |
| `--surface-2` | Sub-surface (sunken inputs, alerts) |
| `--ink` | Primary text |
| `--mute` | Secondary / metadata text |
| `--border` | Borders + hairlines |
| `--accent` / `--accent-fg` | Primary action |
| `--success`, `--destructive`, `--warn-bg` | Semantic tints |
| `--focus-ring` | `*:focus-visible` outline |
| `--r-1`, `--r-2`, `--r-3`, `--r-pill` | Radii scale |

Light-mode variants are deferred (gotcha #74) — `themeStore` may
report `'light'` based on stored preference but the page renders dark
until the light vars land.

## Lighthouse CI auth-cookie pattern

`lighthouserc.cjs` (root) audits `/login` (unauth) + 9
authenticated-shell URLs. Authenticated URLs require the
`iguana_session` cookie. The CI workflow
(`.github/workflows/openapi-types.yml` job `lighthouse`) wires this:

1. Boot `apps/web/tests-e2e/mock-fastapi.mjs` on port 9999.
2. POST `/api/v1/auth/login` to capture the `Set-Cookie` value.
3. Boot `pnpm dev` with `IGUANATRADER_API_BASE_URL=http://127.0.0.1:9999`
   so `hooks.server.ts` proxies `/api/v1/auth/me` against the mock.
4. Run `pnpm exec lhci autorun --collect.headers="Cookie=iguana_session=$VALUE"`.

Locally:

```sh
# In one terminal:
node apps/web/tests-e2e/mock-fastapi.mjs

# In another:
COOKIE_VALUE=$(curl -s -i \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@example.com","password":"correct horse battery staple"}' \
  http://127.0.0.1:9999/api/v1/auth/login \
  | grep -i '^Set-Cookie:' | sed -E 's/.*iguana_session=([^;]+).*/\1/')

IGUANATRADER_API_BASE_URL=http://127.0.0.1:9999 \
  pnpm exec lhci autorun --collect.headers="Cookie=iguana_session=$COOKIE_VALUE"
```

The a11y assertion fails the run if any audited URL drops below
**0.95**. Perf / best-practices / seo are informational only (dev-mode
rendering inflates perf cost — slice 5 design D7).

## Playwright e2e

See `tests-e2e/README.md` for the dual-server pattern. New W1 specs:

- `dashboard-skeleton.spec.ts` — authenticated shell + 8 stubs.
- `sidebar-dynamic.spec.ts` — fixture-driven anti-collision verification.
- `error-boundary.spec.ts` — fixture-driven `+error.svelte` rendering.
- `theme-toggle.spec.ts` — theme store + persistence.

```sh
pnpm --filter @iguanatrader/web e2e:install   # one-shot chromium download
pnpm --filter @iguanatrader/web e2e            # headless run
pnpm --filter @iguanatrader/web e2e:headed     # open chromium window
```

Visual baselines under `tests-e2e/screenshots/` are first-run captured
+ checked into git (slice 4 pattern).
