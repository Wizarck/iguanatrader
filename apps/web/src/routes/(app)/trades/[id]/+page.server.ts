/**
 * Trade detail loader (slice trades-list-and-detail).
 *
 * Fetches `/trades/{id}` + `/trades/{id}/fills` in parallel. Either
 * call failing (4xx/5xx or network throw) → returns `loadError` so
 * the page renders the alert without crashing.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type { FillListOut, FillOut, TradeOut } from '$lib/trades/types';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, cookies, params }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  const headers = sessionCookie
    ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` }
    : undefined;
  const tradeUrl = `${API_BASE_URL}/api/v1/trades/${params.id}`;
  const fillsUrl = `${API_BASE_URL}/api/v1/trades/${params.id}/fills`;

  try {
    const [tradeRes, fillsRes] = await Promise.all([
      fetch(tradeUrl, { headers }),
      fetch(fillsUrl, { headers })
    ]);
    if (!tradeRes.ok) {
      return {
        trade: null,
        fills: [] as FillOut[],
        loadError: `No se pudo cargar el trade: ${tradeRes.status} ${tradeRes.statusText}`
      };
    }
    if (!fillsRes.ok) {
      return {
        trade: null,
        fills: [] as FillOut[],
        loadError: `No se pudieron cargar los fills: ${fillsRes.status} ${fillsRes.statusText}`
      };
    }
    const trade = (await tradeRes.json()) as TradeOut;
    const fillsBody = (await fillsRes.json()) as FillListOut;
    return {
      trade,
      fills: fillsBody.items,
      loadError: null
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      trade: null,
      fills: [] as FillOut[],
      loadError: `No se pudo cargar el trade: ${message}`
    };
  }
};
