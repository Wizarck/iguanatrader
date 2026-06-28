/**
 * Slice W1 (`dashboard-svelte-skeleton`) — authenticated shell e2e.
 *
 * Asserts:
 * - Login + redirect-to lands on the (app) shell.
 * - Sidebar enumerates all 8 domain links in the canonical order.
 * - TopBar renders with theme toggle + ConnectionIndicator.
 * - KillSwitchSlot exists in markup but is empty (W1 contract; K1 fills).
 * - Each domain page renders the `loading…` stub with `aria-busy="true"`.
 *
 * Dual-server (mock-fastapi + Vite dev) per slice 4's pattern; consumed
 * unchanged from `playwright.config.ts`.
 */

import { expect, test } from '@playwright/test';

const VALID_EMAIL = 'alice@example.com';
const VALID_PASSWORD = 'correct horse battery staple';

const DOMAIN_ORDER = [
  { href: '/portfolio', label: 'Portfolio' },
  { href: '/trades', label: 'Trades' },
  { href: '/strategies', label: 'Strategies' },
  { href: '/research', label: 'Research' },
  { href: '/approvals', label: 'Approvals' },
  { href: '/risk', label: 'Risk' },
  { href: '/costs', label: 'Costs' },
  { href: '/settings', label: 'Settings' },
] as const;

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

test.describe('dashboard skeleton', () => {
  test('authenticated shell renders Sidebar + TopBar + 8 stubs', async ({ page }) => {
    await login(page, '/');

    // Sidebar landmark.
    const sidebar = page.getByRole('navigation', { name: /primary/i });
    await expect(sidebar).toBeVisible();

    // 8 domain links in canonical order. We verify each link's
    // accessible name matches the expected label and the order in the
    // DOM matches the canonical sequence.
    const links = sidebar.getByRole('link');
    const expectedLabels = DOMAIN_ORDER.map((d) => d.label);
    await expect(links).toHaveCount(expectedLabels.length);
    for (let i = 0; i < expectedLabels.length; i += 1) {
      await expect(links.nth(i)).toHaveAccessibleName(new RegExp(expectedLabels[i], 'i'));
    }

    // TopBar landmark.
    const topbar = page.getByRole('banner').or(page.locator('header[aria-label="Top bar"]'));
    await expect(topbar.first()).toBeVisible();

    // Email visible in TopBar.
    await expect(page.getByText(VALID_EMAIL)).toBeVisible();

    // ConnectionIndicator visible (status role; aria-label "Data connection:
    // …" — "No data connection" initially, no streams active).
    await expect(page.getByRole('status', { name: /data connection/i })).toBeVisible();

    // KillSwitchSlot exists but is empty (W1 contract — K1 fills).
    const killSlot = page.locator('[data-slot="kill-switch"]');
    await expect(killSlot).toHaveCount(1);
    await expect(killSlot).toBeEmpty();

    await page.screenshot({
      path: 'tests-e2e/screenshots/05-dashboard-empty-shell.png',
      fullPage: true,
    });
  });

  test('each of 8 domain stubs renders loading… with aria-busy', async ({ page }) => {
    await login(page, '/');

    for (const { href, label } of DOMAIN_ORDER) {
      await page.goto(href);
      // The stub renders `<section aria-busy="true">` containing
      // `<h1>{label}</h1>` + `<p>loading…</p>`.
      await expect(
        page.getByRole('heading', { name: new RegExp(`^${label}$`, 'i') }),
      ).toBeVisible();
      await expect(page.getByText(/loading…/i)).toBeVisible();
      const busySection = page.locator('section[aria-busy="true"]').first();
      await expect(busySection).toBeVisible();
    }
  });

  test('sidebar collapsed state persists across reload', async ({ page }) => {
    await login(page, '/');

    const toggle = page.getByRole('button', {
      name: /(collapse|expand) sidebar/i,
    });
    // Initial: expanded.
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');

    // Reload — collapsed state should hydrate from localStorage.
    await page.reload();
    const toggleAfter = page.getByRole('button', {
      name: /(collapse|expand) sidebar/i,
    });
    await expect(toggleAfter).toHaveAttribute('aria-expanded', 'false');

    await page.screenshot({
      path: 'tests-e2e/screenshots/06-dashboard-sidebar-collapsed.png',
      fullPage: true,
    });
  });
});
