/**
 * Broker types catalogue loader (slice ``frontend-broker-mcp-risk-pages``).
 *
 * Calls ``GET /api/v1/broker/types`` with the session cookie. Renders
 * the prose catalogue so an operator can study what sec_type /
 * order_type / algo_kind values the daemon accepts without leaving
 * the app.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type { BrokerTypesResponse } from '$lib/broker/types';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/broker/types`, {
      headers: sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : {}
    });
    if (!res.ok) {
      return {
        catalogue: null as BrokerTypesResponse | null,
        loadError: `No se pudo cargar el catálogo IBKR: ${res.status} ${res.statusText}`
      };
    }
    const catalogue = (await res.json()) as BrokerTypesResponse;
    return { catalogue, loadError: null };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      catalogue: null as BrokerTypesResponse | null,
      loadError: `No se pudo cargar el catálogo IBKR: ${message}`
    };
  }
};
