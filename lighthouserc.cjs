// Lighthouse CI configuration — slice 5 (api-foundation-rfc7807).
//
// Wired by `.github/workflows/openapi-types.yml` (job: lighthouse). Boots
// `pnpm --filter @iguanatrader/web dev` (Vite dev server on :5173) and runs
// Lighthouse against the login surface — the only frontend route slice 4
// shipped. Slice W1 (`dashboard-svelte-skeleton`) appends `/portfolio`,
// `/approval`, etc. as the dashboard family lands.
//
// Per design D7: only a11y is a hard gate (>= 90); perf / best-practices /
// seo are informational baselines (dev-mode rendering inflates perf cost
// because there is no minification + extra source-map overhead).

module.exports = {
  ci: {
    collect: {
      startServerCommand: "pnpm --filter @iguanatrader/web dev --host 127.0.0.1 --port 5173",
      startServerReadyPattern: "Local:",
      startServerReadyTimeout: 60000,
      url: ["http://localhost:5173/login"],
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
        // Hard gate: a11y >= 90 (slice W1 may bump to 95 once the
        // dashboard surface is non-trivial).
        "categories:accessibility": ["error", { minScore: 0.9 }],

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
