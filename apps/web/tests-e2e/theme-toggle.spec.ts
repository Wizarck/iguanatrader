/**
 * Slice W1 — theme store + toggle behaviour.
 *
 * Verifies:
 * - First load sets `<html data-theme="dark">`.
 * - Click the TopBar theme toggle → attribute updates.
 * - Reload → localStorage persists the choice.
 *
 * Light-variant CSS vars are deferred (gotcha #34); the attribute
 * still flips so the contract is exercised.
 */

import { expect, test } from '@playwright/test';

const VALID_EMAIL = 'alice@example.com';
const VALID_PASSWORD = 'correct horse battery staple';

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

test.describe('theme toggle', () => {
  test('initial dark + toggle to light + persistence across reload', async ({ page }) => {
    await login(page, '/');

    // Initial: dark.
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

    // Toggle.
    const toggle = page.getByRole('button', {
      name: /switch to light theme/i,
    });
    await toggle.click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

    // Persist across reload.
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

    // Toggle back to dark.
    const toggleBack = page.getByRole('button', {
      name: /switch to dark theme/i,
    });
    await toggleBack.click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

    await page.screenshot({
      path: 'tests-e2e/screenshots/09-theme-toggle-states.png',
      fullPage: true,
    });
  });
});
