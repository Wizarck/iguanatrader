/**
 * Strategies list page loader (slice strategies-config-ui).
 *
 * Calls `GET ${API_BASE_URL}/api/v1/strategies` with the session cookie
 * forwarded (same shape as `(app)/trades/+page.server.ts`). Surfaces a
 * `loadError` string on non-2xx so the page can render the alert in
 * lieu of a table.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type { StrategyConfigListOut, StrategyConfigOut } from '$lib/strategies/types';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/strategies`, {
      headers: sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : {},
    });
    if (!res.ok) {
      return {
        strategies: [] as StrategyConfigOut[],
        total: 0,
        loadError: `No se pudieron cargar las estrategias: ${res.status} ${res.statusText}`,
      };
    }
    const body = (await res.json()) as StrategyConfigListOut;
    return {
      strategies: body.items,
      total: body.total ?? body.items.length,
      loadError: null,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      strategies: [] as StrategyConfigOut[],
      total: 0,
      loadError: `No se pudieron cargar las estrategias: ${message}`,
    };
  }
};
