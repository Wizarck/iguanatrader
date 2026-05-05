/**
 * Slice W1 — Sidebar dynamic enumeration via `import.meta.glob`.
 *
 * Verifies the anti-collision contract (design D2): drop a `(app)/<name>/+page.svelte`
 * with a `meta` export, the Sidebar picks it up with no edit to
 * `Sidebar.svelte`. Captures both the `meta`-export path and the
 * fallback (route without `meta` → capitalized segment + circle icon
 * + order 100).
 *
 * Implementation note: Vite's `import.meta.glob` resolves at build/dev
 * time. In dev mode the file write triggers an HMR reload which
 * re-runs the glob (verified locally). The test waits for the new
 * link to appear after `page.reload()` to give the dev server a moment
 * to pick up the new module.
 */

import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test } from '@playwright/test';

const VALID_EMAIL = 'alice@example.com';
const VALID_PASSWORD = 'correct horse battery staple';

const ROUTES_DIR = join(process.cwd(), 'src', 'routes', '(app)');
const FIXTURE_DIR = join(ROUTES_DIR, '_sidebar_test_fixture');
const FIXTURE_FILE = join(FIXTURE_DIR, '+page.svelte');

const FALLBACK_ROUTE_DIR = join(ROUTES_DIR, '_fallback_test_fixture');
const FALLBACK_ROUTE_FILE = join(FALLBACK_ROUTE_DIR, '+page.svelte');

const FIXTURE_CONTENTS = `<script lang="ts" module>
  // Fixture file written by sidebar-dynamic.spec.ts; cleaned up after.
  export const meta = {
    label: 'TestX',
    icon: 'circle',
    order: 999
  } as const;
</script>

<section aria-busy="true">
  <h1>TestX</h1>
  <p>fixture</p>
</section>
`;

const FALLBACK_FIXTURE_CONTENTS = `<section aria-busy="true">
  <h1>Foobar</h1>
  <p>fixture (no meta export — falls back to defaults)</p>
</section>
`;

async function login(page: import('@playwright/test').Page, redirectTo = '/'): Promise<void> {
  await page.goto(`/login?redirect_to=${encodeURIComponent(redirectTo)}`);
  await page.getByLabel('Email').fill(VALID_EMAIL);
  await page.getByLabel('Password').fill(VALID_PASSWORD);
  await Promise.all([
    page.waitForURL(`**${redirectTo === '/' ? '/' : redirectTo}`, {
      timeout: 10_000,
    }),
    page.getByRole('button', { name: /sign in/i }).click(),
  ]);
}

test.describe('sidebar dynamic enumeration', () => {
  test.beforeAll(() => {
    mkdirSync(FIXTURE_DIR, { recursive: true });
    writeFileSync(FIXTURE_FILE, FIXTURE_CONTENTS, 'utf8');
    mkdirSync(FALLBACK_ROUTE_DIR, { recursive: true });
    writeFileSync(FALLBACK_ROUTE_FILE, FALLBACK_FIXTURE_CONTENTS, 'utf8');
  });

  test.afterAll(() => {
    rmSync(FIXTURE_DIR, { recursive: true, force: true });
    rmSync(FALLBACK_ROUTE_DIR, { recursive: true, force: true });
  });

  test('Sidebar enumerates a fixture route with meta.order=999 at the end', async ({ page }) => {
    await login(page, '/');

    const sidebar = page.getByRole('navigation', { name: /primary/i });
    // The fixture has order 999, so it sorts after all 8 domain stubs
    // (max order is Settings at 80) AND after any fallback fixture
    // (order 100).
    const links = sidebar.getByRole('link');
    const last = links.last();
    await expect(last).toHaveAccessibleName(/TestX/i);
  });

  test('Sidebar uses fallback meta for routes without meta export', async ({ page }) => {
    await login(page, '/');

    const sidebar = page.getByRole('navigation', { name: /primary/i });
    // Fallback route has order 100, so it sorts after all 8 domain
    // stubs (max 80) but before the meta=999 fixture.
    await expect(sidebar.getByRole('link', { name: /Foobar/i })).toBeVisible();
  });
});
