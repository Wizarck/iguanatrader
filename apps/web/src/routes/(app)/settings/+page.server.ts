/**
 * Settings page loader (slice research-frontend-settings-page).
 *
 * Fetches `/api/v1/settings/feature-flags` (slice R6 backend). On
 * non-2xx returns a default (all flags off) plus an error string so
 * the page can still render the toggle UI in a degraded state.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';

import type { PageServerLoad } from './$types';

export type FeatureFlags = {
  hindsight_recall_enabled: boolean;
};

export const load: PageServerLoad = async ({ fetch, cookies }) => {
  // SvelteKit's `fetch` resolves relative URLs against the SvelteKit
  // origin, so `/api/v1/...` would land on the web container which has
  // no such route (→ 404). Hit the API via its docker-network URL and
  // forward the session cookie so the auth middleware accepts the call.
  const sessionCookie = cookies.get(COOKIE_NAME);
  const res = await fetch(`${API_BASE_URL}/api/v1/settings/feature-flags`, {
    headers: sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : {}
  });
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
