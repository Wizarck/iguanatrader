/**
 * Slice W1 — global +error.svelte renders RFC 7807 Problem.
 *
 * Drops two fixture routes at test-scope under (app):
 *   - `_error_404_fixture/+page.server.ts` calls `error(404, problem)`
 *     where `problem` is a Problem-shaped body.
 *   - `_error_500_fixture/+page.server.ts` calls `error(500, problem)`
 *     with `correlation_id` so the copy-button branch renders.
 *
 * Verifies +error.svelte:
 *   - renders `role="alert"` + `aria-live="polite"` markup;
 *   - renders the title + status + detail;
 *   - shows the type URI badge;
 *   - shows the correlation ID + copy button on 500.
 */

import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test } from '@playwright/test';

const VALID_EMAIL = 'alice@example.com';
const VALID_PASSWORD = 'correct horse battery staple';

const ROUTES_DIR = join(process.cwd(), 'src', 'routes', '(app)');

const FIXTURE_404_DIR = join(ROUTES_DIR, '_error_404_fixture');
const FIXTURE_404_LOAD = join(FIXTURE_404_DIR, '+page.server.ts');
const FIXTURE_404_PAGE = join(FIXTURE_404_DIR, '+page.svelte');

const FIXTURE_500_DIR = join(ROUTES_DIR, '_error_500_fixture');
const FIXTURE_500_LOAD = join(FIXTURE_500_DIR, '+page.server.ts');
const FIXTURE_500_PAGE = join(FIXTURE_500_DIR, '+page.svelte');

const LOAD_404 = `import { error } from '@sveltejs/kit';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = () => {
  throw error(404, {
    message: 'Not Found — fixture',
    type: 'urn:iguanatrader:error:not-found',
    title: 'Not Found',
    status: 404,
    detail: 'Trade ID 999 does not exist (fixture).'
  } as App.Error);
};
`;

const LOAD_500 = `import { error } from '@sveltejs/kit';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = () => {
  throw error(500, {
    message: 'Internal — fixture',
    type: 'urn:iguanatrader:error:internal',
    title: 'Internal Error',
    status: 500,
    detail: 'Database connection lost (fixture).',
    correlation_id: 'req-fixture-abc-123'
  } as App.Error);
};
`;

const PLACEHOLDER_PAGE = `<p>placeholder — load function always errors</p>
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

test.describe('+error.svelte global boundary', () => {
  test.beforeAll(() => {
    mkdirSync(FIXTURE_404_DIR, { recursive: true });
    writeFileSync(FIXTURE_404_LOAD, LOAD_404, 'utf8');
    writeFileSync(FIXTURE_404_PAGE, PLACEHOLDER_PAGE, 'utf8');

    mkdirSync(FIXTURE_500_DIR, { recursive: true });
    writeFileSync(FIXTURE_500_LOAD, LOAD_500, 'utf8');
    writeFileSync(FIXTURE_500_PAGE, PLACEHOLDER_PAGE, 'utf8');
  });

  test.afterAll(() => {
    rmSync(FIXTURE_404_DIR, { recursive: true, force: true });
    rmSync(FIXTURE_500_DIR, { recursive: true, force: true });
  });

  test('404 renders Problem with action hint (recoverable variant)', async ({ page }) => {
    await login(page, '/');
    await page.goto('/_error_404_fixture');

    const alert = page.getByRole('alert');
    await expect(alert).toBeVisible();
    await expect(alert.getByRole('heading', { name: /not found/i })).toBeVisible();
    await expect(alert).toContainText(/Status 404/i);
    await expect(alert).toContainText(/Trade ID 999/);
    await expect(alert).toContainText(/urn:iguanatrader:error:not-found/);
    // Recoverable: "Go home" link.
    await expect(alert.getByRole('link', { name: /go home/i })).toBeVisible();

    await page.screenshot({
      path: 'tests-e2e/screenshots/07-error-boundary-404.png',
      fullPage: true,
    });
  });

  test('500 renders Problem with correlation ID + copy button (unrecoverable)', async ({
    page,
  }) => {
    await login(page, '/');
    await page.goto('/_error_500_fixture');

    const alert = page.getByRole('alert');
    await expect(alert).toBeVisible();
    await expect(alert.getByRole('heading', { name: /internal error/i })).toBeVisible();
    await expect(alert).toContainText(/Status 500/i);
    await expect(alert).toContainText('req-fixture-abc-123');
    await expect(alert.getByRole('button', { name: /copy correlation id/i })).toBeVisible();
    // Unrecoverable: "Try again" link.
    await expect(alert.getByRole('link', { name: /try again/i })).toBeVisible();

    await page.screenshot({
      path: 'tests-e2e/screenshots/08-error-boundary-500.png',
      fullPage: true,
    });
  });
});
