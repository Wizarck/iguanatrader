/**
 * Pure-logic helpers for `PasswordAgeingBanner.svelte`
 * (slice `auth-password-aging-warning`).
 *
 * The component itself is a thin render layer; all branching lives here
 * so the suite can unit-test the decision matrix without DOM (vitest
 * runs under `environment: 'node'` in `vite.config.ts`).
 */

export type PasswordAgeingState = 'fresh' | 'ageing' | 'stale';

export type BannerVariant = {
  /** ARIA live-region role: `status` for soft, `alert` for assertive. */
  role: 'status' | 'alert';
  /** CSS modifier appended to `.banner` (e.g. `warning` / `danger`). */
  variant: 'warning' | 'danger';
  /** Sentence shown to the user. Includes the age in days. */
  message: string;
  /** Anchor copy + href. The href is fixed; copy stays consistent. */
  link: { href: string; text: string };
};

/**
 * Compute the banner presentation, or `null` if no banner should render.
 *
 * Contract:
 *
 * - `'fresh'` (default for new accounts + legacy `password_changed_at IS
 *   NULL` rows) → `null` → component renders nothing.
 * - `'ageing'` → `role='status'` + `variant='warning'` + soft copy.
 * - `'stale'` → `role='alert'` + `variant='danger'` + action-requested copy.
 *
 * The link href is hard-coded to `/account/change-password` (the
 * canonical rotation route shipped by slice `auth-change-password`).
 * Tests assert this verbatim so a future move of that route also
 * updates the banner.
 *
 * `ageDays` can be `null` even in the `ageing`/`stale` branches because
 * the backend type allows it (e.g. a future telemetry-only deployment
 * could surface the state without leaking the exact count). When
 * `null`, the message falls back to a count-free sentence.
 */
export function getBannerVariant(
  state: PasswordAgeingState,
  ageDays: number | null
): BannerVariant | null {
  if (state === 'fresh') return null;

  const ageFragment =
    ageDays === null || ageDays === undefined
      ? ''
      : `${ageDays} days old`;

  if (state === 'ageing') {
    const sentence = ageFragment
      ? `Your password is ${ageFragment} — consider rotating it.`
      : 'Your password is approaching the rotation threshold — consider rotating it.';
    return {
      role: 'status',
      variant: 'warning',
      message: sentence,
      link: { href: '/account/change-password', text: 'Change password →' }
    };
  }

  // state === 'stale'
  const staleSentence = ageFragment
    ? `Your password is ${ageFragment}. Please rotate it.`
    : 'Your password is past the rotation threshold. Please rotate it.';
  return {
    role: 'alert',
    variant: 'danger',
    message: staleSentence,
    link: { href: '/account/change-password', text: 'Change password →' }
  };
}
