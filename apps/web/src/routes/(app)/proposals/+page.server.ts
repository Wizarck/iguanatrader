/**
 * Proposals list page loader (slice ``frontend-gaps-batch``).
 *
 * Calls ``GET /api/v1/proposals`` with the session cookie forwarded.
 * The backend route already exists (proposals.py); the UI gap is
 * what this slice closes.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type { ProposalListOut, ProposalOut } from '$lib/proposals/types';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/proposals`, {
      headers: sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : {}
    });
    if (!res.ok) {
      return {
        proposals: [] as ProposalOut[],
        total: 0,
        loadError: `Could not load proposals: ${res.status} ${res.statusText}`
      };
    }
    const body = (await res.json()) as ProposalListOut;
    return {
      proposals: body.items,
      total: body.total ?? body.items.length,
      loadError: null
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      proposals: [] as ProposalOut[],
      total: 0,
      loadError: `Could not load proposals: ${message}`
    };
  }
};
