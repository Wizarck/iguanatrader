/**
 * Costs dashboard loader (slice costs-dashboard-ui).
 *
 * Three parallel upstream fetches against the FastAPI costs surface:
 *   - GET /api/v1/costs/summary      → CostSummaryDTO
 *   - GET /api/v1/costs/by-provider  → CostByProviderDTO
 *   - GET /api/v1/costs/per-trade    → CostPerTradeDTO
 *
 * Any non-2xx or network throw → returns `loadError` so the page renders
 * the alert without crashing (same contract as `portfolio/+page.server.ts`).
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type {
  CostByProviderDTO,
  CostPerTradeDTO,
  CostSummaryDTO,
} from '$lib/costs/types';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  const headers = sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : undefined;

  const summaryUrl = `${API_BASE_URL}/api/v1/costs/summary`;
  const byProviderUrl = `${API_BASE_URL}/api/v1/costs/by-provider`;
  const perTradeUrl = `${API_BASE_URL}/api/v1/costs/per-trade`;

  try {
    const [summaryRes, byProviderRes, perTradeRes] = await Promise.all([
      fetch(summaryUrl, { headers }),
      fetch(byProviderUrl, { headers }),
      fetch(perTradeUrl, { headers }),
    ]);

    if (!summaryRes.ok) {
      return emptyResult(
        `No se pudo cargar el resumen de costes: ${summaryRes.status} ${summaryRes.statusText}`,
      );
    }
    if (!byProviderRes.ok) {
      return emptyResult(
        `No se pudo cargar el desglose por proveedor: ${byProviderRes.status} ${byProviderRes.statusText}`,
      );
    }
    if (!perTradeRes.ok) {
      return emptyResult(
        `No se pudo cargar el coste por trade: ${perTradeRes.status} ${perTradeRes.statusText}`,
      );
    }

    const summary = (await summaryRes.json()) as CostSummaryDTO;
    const byProvider = (await byProviderRes.json()) as CostByProviderDTO;
    const perTrade = (await perTradeRes.json()) as CostPerTradeDTO;

    return {
      summary,
      byProvider,
      perTrade,
      loadError: null,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return emptyResult(`No se pudo cargar el dashboard de costes: ${message}`);
  }
};

function emptyResult(loadError: string): {
  summary: CostSummaryDTO | null;
  byProvider: CostByProviderDTO | null;
  perTrade: CostPerTradeDTO | null;
  loadError: string;
} {
  return {
    summary: null,
    byProvider: null,
    perTrade: null,
    loadError,
  };
}
