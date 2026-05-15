/**
 * Unit tests for the `PasswordAgeingBanner` decision matrix
 * (slice `auth-password-aging-warning`).
 *
 * The Svelte component itself is a thin render layer over
 * `getBannerVariant`; vitest runs under `environment: 'node'` so we
 * exercise the pure helper directly rather than spinning up DOM. The
 * 4 cases from the proposal map 1:1 to a `getBannerVariant` call:
 *
 *   1. renders nothing when fresh (returns `null`).
 *   2. renders warning when ageing (role=`status`, age text in message).
 *   3. renders danger when stale (role=`alert`, "Change password" in link).
 *   4. link points to `/account/change-password` in both visible states.
 */

import { describe, expect, it } from 'vitest';

import { getBannerVariant } from '../src/lib/components/password-ageing-banner';

describe('getBannerVariant', () => {
  it('renders nothing when state is fresh', () => {
    expect(getBannerVariant('fresh', null)).toBeNull();
    expect(getBannerVariant('fresh', 10)).toBeNull();
    expect(getBannerVariant('fresh', 200)).toBeNull();
  });

  it('renders warning banner when ageing (role="status", age in message)', () => {
    const variant = getBannerVariant('ageing', 65);
    expect(variant).not.toBeNull();
    expect(variant!.role).toBe('status');
    expect(variant!.variant).toBe('warning');
    expect(variant!.message).toContain('65 days');
    // Soft copy: "consider rotating" reads as a heads-up, not an order.
    expect(variant!.message.toLowerCase()).toContain('consider');
  });

  it('renders danger banner when stale (role="alert", change-password copy)', () => {
    const variant = getBannerVariant('stale', 95);
    expect(variant).not.toBeNull();
    expect(variant!.role).toBe('alert');
    expect(variant!.variant).toBe('danger');
    expect(variant!.message).toContain('95 days');
    // Action copy on the link, not the body, so screen readers
    // announce the CTA after the assertive sentence.
    expect(variant!.link.text).toContain('Change password');
  });

  it('link points to /account/change-password in both visible states', () => {
    const ageing = getBannerVariant('ageing', 60);
    const stale = getBannerVariant('stale', 90);
    expect(ageing!.link.href).toBe('/account/change-password');
    expect(stale!.link.href).toBe('/account/change-password');
  });
});
