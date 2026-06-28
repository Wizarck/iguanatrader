/**
 * Ingest-runs admin page loader (slice ``frontend-gaps-batch``).
 *
 * Calls ``GET /api/v1/admin/ingest-runs`` with the session cookie
 * forwarded. Optional query string ``?status=error`` lets the
 * operator filter to just the failures.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type { IngestRunListOut, IngestRunOut } from '$lib/admin/types';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, cookies, url }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  const headers = sessionCookie
    ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` }
    : {};
  const status = url.searchParams.get('status');
  const query = status ? `?status=${encodeURIComponent(status)}` : '';
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/admin/ingest-runs${query}`, {
      headers
    });
    if (!res.ok) {
      return {
        runs: [] as IngestRunOut[],
        statusFilter: status,
        loadError: `Could not load ingest runs: ${res.status} ${res.statusText}`
      };
    }
    const body = (await res.json()) as IngestRunListOut;
    return {
      runs: body.items,
      statusFilter: status,
      loadError: null
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      runs: [] as IngestRunOut[],
      statusFilter: status,
      loadError: `Could not load ingest runs: ${message}`
    };
  }
};
