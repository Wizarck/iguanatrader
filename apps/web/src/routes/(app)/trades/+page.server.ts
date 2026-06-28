/**
 * Trades list page loader (slice trades-list-and-detail).
 *
 * Calls `GET ${API_BASE_URL}/api/v1/trades` with the session cookie
 * forwarded (same shape as `(app)/settings/+page.server.ts`). Surfaces
 * a `loadError` string on non-2xx so the page can render the alert in
 * lieu of a table.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type { TradeListOut, TradeOut } from '$lib/trades/types';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/trades`, {
      headers: sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : {}
    });
    if (!res.ok) {
      return {
        trades: [] as TradeOut[],
        total: 0,
        loadError: `Could not load trades: ${res.status} ${res.statusText}`
      };
    }
    const body = (await res.json()) as TradeListOut;
    return {
      trades: body.items,
      total: body.total ?? body.items.length,
      loadError: null
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      trades: [] as TradeOut[],
      total: 0,
      loadError: `Could not load trades: ${message}`
    };
  }
};
