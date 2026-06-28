/**
 * Proposal detail loader (slice ``frontend-gaps-batch``).
 *
 * Fetches ``GET /proposals/{id}`` so the page can render the
 * proposal + offer the explain / risk-review action buttons.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type { ProposalOut } from '$lib/proposals/types';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, cookies, params }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  const headers = sessionCookie
    ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` }
    : undefined;
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/proposals/${params.id}`, { headers });
    if (!res.ok) {
      return {
        proposal: null as ProposalOut | null,
        loadError: `Could not load the proposal: ${res.status} ${res.statusText}`
      };
    }
    const proposal = (await res.json()) as ProposalOut;
    return { proposal, loadError: null };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      proposal: null as ProposalOut | null,
      loadError: `Could not load the proposal: ${message}`
    };
  }
};
