/**
 * Slice research-frontend-extras-2 — audit-trail page e2e.
 *
 * Asserts:
 * - Direct navigation renders BriefHeader + AuditTrailViewer accordion.
 * - Accordion toggle on the first entry exposes formula/inputs/steps/output.
 * - Mismatched ?brief_version redirects to the current version.
 */

import { expect, test } from '@playwright/test';

const VALID_EMAIL = 'alice@example.com';
const VALID_PASSWORD = 'correct horse battery staple';

async function login(page: import('@playwright/test').Page, redirectTo: string): Promise<void> {
  await page.goto(`/login?redirect_to=${encodeURIComponent(redirectTo)}`);
  await page.getByLabel('Email').fill(VALID_EMAIL);
  await page.getByLabel('Password').fill(VALID_PASSWORD);
  await Promise.all([
    page.waitForURL(`**${redirectTo}**`, { timeout: 10_000 }),
    page.getByRole('button', { name: /sign in/i }).click()
  ]);
}

test.describe('research audit trail', () => {
  test('renders accordion + expands on click', async ({ page }) => {
    await login(page, '/research/AAPL/audit-trail/1');

    // BriefHeader (no refresh CTA because refreshDisabled=true on this page).
    await expect(page.getByRole('heading', { name: 'AAPL' })).toBeVisible();
    await expect(page.getByRole('button', { name: /refresh/i })).toHaveCount(0);

    // Audit-trail region with one accordion entry from the mock.
    const region = page.getByRole('region', { name: /audit trail derivation chain/i });
    await expect(region).toBeVisible();
    const toggle = region.getByRole('button', { name: /pe = price \/ earnings/ });
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');

    // Click to expand.
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(region.getByText('Final output')).toBeVisible();
    await expect(region.getByText('180.0 / 6.0 = 30.0')).toBeVisible();
  });

  test('mismatched brief_version redirects to current', async ({ page }) => {
    await login(page, '/research/AAPL/audit-trail/1');
    // Direct navigation to a version that doesn't exist: should land on v1.
    await page.goto('/research/AAPL/audit-trail/9');
    await expect(page).toHaveURL(/\/research\/AAPL\/audit-trail\/1$/);
  });
});
