/**
 * Risk dashboard loader (slice risk-dashboard-ui).
 *
 * Single upstream fetch against the FastAPI risk surface (slice K1):
 *   - GET /api/v1/risk/state → RiskStateResponse
 *
 * Any 5xx, non-2xx, or network throw → returns `loadError` so the
 * page renders the alert without crashing (same contract as
 * `(app)/portfolio/+page.server.ts`).
 *
 * The `POST /risk/override` UI lives in a future slice
 * (`risk-override-ui`) — out of scope here.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type { RiskStateResponse } from '$lib/risk/types';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  const headers = sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : undefined;

  const stateUrl = `${API_BASE_URL}/api/v1/risk/state`;

  try {
    const res = await fetch(stateUrl, { headers });

    if (!res.ok) {
      return emptyResult(`Could not load risk state: ${res.status} ${res.statusText}`);
    }

    const risk = (await res.json()) as RiskStateResponse;

    return {
      risk,
      loadError: null,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return emptyResult(`Could not load risk state: ${message}`);
  }
};

function emptyResult(loadError: string): {
  risk: RiskStateResponse | null;
  loadError: string;
} {
  return {
    risk: null,
    loadError,
  };
}
