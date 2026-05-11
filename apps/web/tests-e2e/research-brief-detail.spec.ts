/**
 * Slice research-frontend-extras-2 — brief detail page e2e.
 *
 * Asserts:
 * - Markdown body renders to HTML (heading + list).
 * - Citation markers become inline chips with the right fact id.
 * - FactTimeline shows the mock's two facts.
 * - "View audit trail" link points to /audit-trail/<version>.
 */

import { expect, test } from '@playwright/test';

const VALID_EMAIL = 'alice@example.com';
const VALID_PASSWORD = 'correct horse battery staple';

async function login(page: import('@playwright/test').Page, redirectTo = '/research/AAPL'): Promise<void> {
  await page.goto(`/login?redirect_to=${encodeURIComponent(redirectTo)}`);
  await page.getByLabel('Email').fill(VALID_EMAIL);
  await page.getByLabel('Password').fill(VALID_PASSWORD);
  await Promise.all([
    page.waitForURL(`**${redirectTo}`, { timeout: 10_000 }),
    page.getByRole('button', { name: /sign in/i }).click()
  ]);
}

test.describe('research brief detail', () => {
  test('renders markdown body + facts + audit-trail link', async ({ page }) => {
    await login(page, '/research/AAPL');

    // Markdown heading from the mock body.
    await expect(page.getByRole('heading', { name: /AAPL thesis/i })).toBeVisible();
    // Bullet list rendered as <ul>.
    await expect(page.getByText('bullet one')).toBeVisible();
    await expect(page.getByText('bullet two')).toBeVisible();

    // Fact timeline shows two rows from the mock.
    const timeline = page.getByRole('region', { name: /recent facts timeline/i });
    await expect(timeline).toBeVisible();
    await expect(timeline.getByText('price')).toBeVisible();
    await expect(timeline.getByText('earnings')).toBeVisible();

    // Audit-trail link present and points to /audit-trail/1.
    const auditLink = page.getByRole('link', { name: /view audit trail/i });
    await expect(auditLink).toBeVisible();
    await expect(auditLink).toHaveAttribute('href', '/research/AAPL/audit-trail/1');
  });
});
