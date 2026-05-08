/**
 * Settings page loader (slice research-frontend-settings-page).
 *
 * Fetches `/api/v1/settings/feature-flags` (slice R6 backend). On
 * non-2xx returns a default (all flags off) plus an error string so
 * the page can still render the toggle UI in a degraded state.
 */

import type { PageServerLoad } from './$types';

export type FeatureFlags = {
  hindsight_recall_enabled: boolean;
};

export const load: PageServerLoad = async ({ fetch }) => {
  const res = await fetch('/api/v1/settings/feature-flags');
  if (!res.ok) {
    return {
      flags: { hindsight_recall_enabled: false } satisfies FeatureFlags,
      loadError: `Failed to load feature flags: ${res.status} ${res.statusText}`
    };
  }
  const flags = (await res.json()) as FeatureFlags;
  return {
    flags,
    loadError: null
  };
};
