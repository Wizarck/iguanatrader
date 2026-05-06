// Lighthouse CI configuration — slice 5 (api-foundation-rfc7807) +
// slice W1 (dashboard-svelte-skeleton).
//
// Wired by `.github/workflows/openapi-types.yml` (job: lighthouse). Boots
// `pnpm --filter @iguanatrader/web dev` (Vite dev server on :5173) and runs
// Lighthouse against the login surface + the W1 authenticated-shell
// stubs (per design D9 + slice 5 design Q2 deferred answer).
//
// Per slice 5 design D7 + W1 design D9: only a11y is a hard gate
// (>= 0.95 from W1; was 0.90 in slice 5). Perf / best-practices / seo
// are informational baselines (dev-mode rendering inflates perf cost
// because there is no minification + extra source-map overhead).
//
// **Authenticated URLs**: the lhci collect step in CI must set a
// session cookie before the audit (POST /api/v1/auth/login against the
// mock-fastapi or real backend, capture the iguana_session cookie,
// pass via `--collect.headers='Cookie: iguana_session=<value>'`). The
// pattern is documented in `apps/web/README.md`. Locally, run with the
// dev server already authenticated or pass the cookie via env.

module.exports = {
  ci: {
    collect: {
      startServerCommand:
        "pnpm --filter @iguanatrader/web dev --host 127.0.0.1 --port 5173",
      startServerReadyPattern: "Local:",
      startServerReadyTimeout: 60000,
      url: [
        // Slice 4-5 — unauthenticated.
        "http://localhost:5173/login",

        // Slice W1 — authenticated-shell stubs. Require the session
        // cookie (set via `--collect.headers='Cookie: iguana_session=<value>'`
        // in the workflow step).
        "http://localhost:5173/",
        "http://localhost:5173/portfolio",
        "http://localhost:5173/research",
        "http://localhost:5173/trades",
        "http://localhost:5173/strategies",
        "http://localhost:5173/approvals",
        "http://localhost:5173/risk",
        "http://localhost:5173/costs",
        "http://localhost:5173/settings",
      ],
      numberOfRuns: 1,
      settings: {
        // Dev-mode the network is local, but Lighthouse still applies its
        // default throttling profile. Disable to keep perf scores
        // deterministic across runners.
        throttlingMethod: "provided",
        chromeFlags: "--no-sandbox --headless=new",
      },
    },
    assert: {
      assertions: {
        // Hard gate: a11y >= 0.95 (slice W1 bumped from slice 5's 0.90 —
        // dashboard skeleton has enough surface to assert tighter rules).
        "categories:accessibility": ["error", { minScore: 0.95 }],

        // Informational baselines — surfaced in the workflow artefact
        // but never fail the run on these (dev-mode skews perf).
        "categories:performance": "off",
        "categories:best-practices": "off",
        "categories:seo": "off",
      },
    },
    upload: {
      target: "filesystem",
      outputDir: ".lighthouseci",
    },
  },
};
