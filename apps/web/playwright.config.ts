import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config — slice 4 ``auth-jwt-cookie`` e2e harness.
 *
 * Two webServers run in parallel:
 *
 * 1. ``mock-fastapi.mjs`` on port 9999 — minimal node http server
 *    impersonating the FastAPI auth endpoints. The real Python
 *    backend isn't reachable from this suite (poetry.lock regen lands
 *    at end-of-slice in task 1.6); the mock keeps the e2e walk
 *    independent of backend state.
 *
 * 2. SvelteKit dev server on port 5173 with
 *    ``IGUANATRADER_API_BASE_URL`` pointing at the mock so the
 *    form-action's server-side fetch lands on the mock.
 *
 * The single screenshot subdir ``tests-e2e/screenshots/`` is checked
 * into git as visual regression baselines. Slice W1 may extend this
 * with @playwright/expect's toHaveScreenshot for full-page diffing.
 */
export default defineConfig({
  testDir: './tests-e2e',
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off'
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    }
  ],
  webServer: [
    {
      command: 'node tests-e2e/mock-fastapi.mjs',
      port: 9999,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
      stderr: 'pipe',
      env: { MOCK_API_PORT: '9999' }
    },
    {
      command: 'pnpm dev --port 5173 --strictPort',
      port: 5173,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
      stderr: 'pipe',
      env: { IGUANATRADER_API_BASE_URL: 'http://127.0.0.1:9999' }
    }
  ]
});
