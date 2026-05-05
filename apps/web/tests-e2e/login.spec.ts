/**
 * Slice 4 ``auth-jwt-cookie`` Playwright e2e — full browser-side flow.
 *
 * This walk covers what vitest can't: real cookie storage + propagation
 * by the user-agent, real form submit hitting the SvelteKit form
 * action which proxies to the mock FastAPI backend, real redirect
 * handling by the browser, real DOM rendering of the post-login
 * surface.
 *
 * Visual baselines land at ``tests-e2e/screenshots/`` and are checked
 * into git so future slices can diff against them.
 *
 * Spec scenarios covered:
 *
 * * "Authenticated request to (app) route" → cold visit redirects.
 * * "Successful login from form action" → form submit → 302 to
 *   `redirect_to` → cookie travels back → /me round-trips → portfolio
 *   stub renders the user's email.
 */

import { expect, test } from '@playwright/test';

const VALID_EMAIL = 'alice@example.com';
const VALID_PASSWORD = 'correct horse battery staple';

test.describe('login → redirect-after-login', () => {
  test('cold visit to /portfolio redirects to /login with redirect_to', async ({
    page
  }) => {
    await page.goto('/portfolio?range=last-7d');

    // hooks.server.ts must 302 us to /login?redirect_to=<encoded>.
    await expect(page).toHaveURL(
      /\/login\?redirect_to=%2Fportfolio%3Frange%3Dlast-7d/
    );

    // Login card renders with the OKLCH-token brand.
    await expect(page.getByText('iguanatrader').first()).toBeVisible();
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();

    await page.screenshot({
      path: 'tests-e2e/screenshots/01-login-cold-visit.png',
      fullPage: true
    });
  });

  test('valid credentials → portfolio with cookie + email visible', async ({
    page
  }) => {
    // Cold visit (gets us to /login?redirect_to=%2Fportfolio).
    await page.goto('/portfolio');
    await expect(page).toHaveURL(/\/login\?redirect_to=%2Fportfolio/);

    // Fill + submit the form.
    await page.getByLabel('Email').fill(VALID_EMAIL);
    await page.getByLabel('Password').fill(VALID_PASSWORD);

    await page.screenshot({
      path: 'tests-e2e/screenshots/02-login-form-filled.png',
      fullPage: true
    });

    await Promise.all([
      page.waitForURL('**/portfolio', { timeout: 10_000 }),
      page.getByRole('button', { name: /sign in/i }).click()
    ]);

    // Land on /portfolio with the user's email rendered in the stub.
    await expect(page.getByRole('heading', { name: /portfolio/i })).toBeVisible();
    await expect(page.getByText(VALID_EMAIL)).toBeVisible();

    // Cookie present + flagged correctly.
    const cookies = await page.context().cookies();
    const session = cookies.find((c) => c.name === 'iguana_session');
    expect(session).toBeDefined();
    expect(session!.httpOnly).toBe(true);
    expect(session!.sameSite).toBe('Strict');

    await page.screenshot({
      path: 'tests-e2e/screenshots/03-portfolio-after-login.png',
      fullPage: true
    });
  });

  test('wrong password → destructive Alert + stays on /login', async ({
    page
  }) => {
    await page.goto('/login');

    await page.getByLabel('Email').fill(VALID_EMAIL);
    await page.getByLabel('Password').fill('definitely-wrong');
    await page.getByRole('button', { name: /sign in/i }).click();

    // Alert renders, URL still /login.
    await expect(page.getByRole('alert')).toContainText(/Invalid/i);
    await expect(page).toHaveURL(/\/login/);

    await page.screenshot({
      path: 'tests-e2e/screenshots/04-login-wrong-password.png',
      fullPage: true
    });
  });
});
