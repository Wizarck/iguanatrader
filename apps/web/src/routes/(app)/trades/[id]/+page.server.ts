/**
 * Trade detail loader (slice trades-list-and-detail).
 *
 * Fetches `/trades/{id}` + `/trades/{id}/fills` in parallel. Either
 * call failing (4xx/5xx or network throw) → returns `loadError` so
 * the page renders the alert without crashing.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type { FillListOut, FillOut, OrderListOut, OrderOut, TradeOut } from '$lib/trades/types';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, cookies, params }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  const headers = sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : undefined;
  const tradeUrl = `${API_BASE_URL}/api/v1/trades/${params.id}`;
  const fillsUrl = `${API_BASE_URL}/api/v1/trades/${params.id}/fills`;
  // Slice u-next-2-trade-timeline: pull the orders for the timeline
  // section. Orders endpoint is forgiving (empty list when entry
  // hasn't been submitted) so a 404 short-circuits to loadError but
  // an empty list does not.
  const ordersUrl = `${API_BASE_URL}/api/v1/trades/${params.id}/orders`;

  try {
    const [tradeRes, fillsRes, ordersRes] = await Promise.all([
      fetch(tradeUrl, { headers }),
      fetch(fillsUrl, { headers }),
      fetch(ordersUrl, { headers }),
    ]);
    if (!tradeRes.ok) {
      return {
        trade: null,
        fills: [] as FillOut[],
        orders: [] as OrderOut[],
        loadError: `Could not load the trade: ${tradeRes.status} ${tradeRes.statusText}`,
      };
    }
    if (!fillsRes.ok) {
      return {
        trade: null,
        fills: [] as FillOut[],
        orders: [] as OrderOut[],
        loadError: `Could not load fills: ${fillsRes.status} ${fillsRes.statusText}`,
      };
    }
    if (!ordersRes.ok) {
      return {
        trade: null,
        fills: [] as FillOut[],
        orders: [] as OrderOut[],
        loadError: `Could not load orders: ${ordersRes.status} ${ordersRes.statusText}`,
      };
    }
    const trade = (await tradeRes.json()) as TradeOut;
    const fillsBody = (await fillsRes.json()) as FillListOut;
    const ordersBody = (await ordersRes.json()) as OrderListOut;
    return {
      trade,
      fills: fillsBody.items,
      orders: ordersBody.items,
      loadError: null,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      trade: null,
      fills: [] as FillOut[],
      orders: [] as OrderOut[],
      loadError: `Could not load the trade: ${message}`,
    };
  }
};
