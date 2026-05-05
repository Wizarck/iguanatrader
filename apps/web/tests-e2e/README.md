# `apps/web/tests-e2e/`

Playwright e2e suite for the slice 4 `auth-jwt-cookie` user-agent flow.

Two webServers spin up in parallel (declared in `playwright.config.ts`):

- **mock-fastapi** (port 9999): an in-process node `http.createServer`
  impersonating the FastAPI auth endpoints. The real Python backend
  isn't reachable from this suite (poetry.lock regen lands at
  end-of-slice); the mock keeps e2e independent of backend state.
- **vite dev** (port 5173): the SvelteKit dev server with
  `IGUANATRADER_API_BASE_URL` pointing at the mock.

## Running locally

First-time setup:

```sh
pnpm --filter @iguanatrader/web install
pnpm --filter @iguanatrader/web e2e:install   # downloads chromium binary (~300MB)
```

Run the suite:

```sh
pnpm --filter @iguanatrader/web e2e            # headless
pnpm --filter @iguanatrader/web e2e:headed     # open chromium window
```

After the run, the HTML report lives at `playwright-report/index.html`
(gitignored).

## Visual baselines

`tests-e2e/screenshots/*.png` files are checked in so future slices can
diff against them. Slice W1 may extend this with `expect(page).toHaveScreenshot()`
for full-page diffing.

## Mocked credentials

The mock backend accepts exactly one login pair:

- email: `alice@example.com`
- password: `correct horse battery staple`

Anything else returns 401. The same constants are duplicated across the
spec files and `mock-fastapi.mjs` — keep them in sync if either changes.
