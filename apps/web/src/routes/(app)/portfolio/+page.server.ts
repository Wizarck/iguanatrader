/**
 * Portfolio dashboard loader (slice portfolio-dashboard-mvp).
 *
 * Three parallel upstream fetches against the FastAPI portfolio surface:
 *   - GET /api/v1/portfolio                       → PortfolioSummaryOut
 *   - GET /api/v1/portfolio/positions             → PositionListOut
 *   - GET /api/v1/portfolio/equity/series?days=30 → EquitySnapshotListOut
 *
 * Any 5xx, non-2xx, or network throw → returns `loadError` so the page
 * renders the alert without crashing (same contract as
 * `(app)/trades/+page.server.ts`).
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type {
  EquitySnapshotListOut,
  EquitySnapshotOut,
  PortfolioSummaryOut,
  PositionListOut,
  PositionOut,
} from '$lib/portfolio/types';

import type { PageServerLoad } from './$types';

const EQUITY_SERIES_DAYS = 30;

export const load: PageServerLoad = async ({ fetch, cookies }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  const headers = sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : undefined;

  const summaryUrl = `${API_BASE_URL}/api/v1/portfolio`;
  const positionsUrl = `${API_BASE_URL}/api/v1/portfolio/positions`;
  const seriesUrl = `${API_BASE_URL}/api/v1/portfolio/equity/series?days=${EQUITY_SERIES_DAYS}`;

  try {
    const [summaryRes, positionsRes, seriesRes] = await Promise.all([
      fetch(summaryUrl, { headers }),
      fetch(positionsUrl, { headers }),
      fetch(seriesUrl, { headers }),
    ]);

    if (!summaryRes.ok) {
      return emptyResult(
        `No se pudo cargar el portfolio: ${summaryRes.status} ${summaryRes.statusText}`,
      );
    }
    if (!positionsRes.ok) {
      return emptyResult(
        `No se pudieron cargar las posiciones: ${positionsRes.status} ${positionsRes.statusText}`,
      );
    }
    if (!seriesRes.ok) {
      return emptyResult(
        `No se pudo cargar la serie de equity: ${seriesRes.status} ${seriesRes.statusText}`,
      );
    }

    const summary = (await summaryRes.json()) as PortfolioSummaryOut;
    const positionsBody = (await positionsRes.json()) as PositionListOut;
    const seriesBody = (await seriesRes.json()) as EquitySnapshotListOut;

    return {
      summary,
      positions: positionsBody.items,
      equity_series: seriesBody.items,
      loadError: null,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return emptyResult(`No se pudo cargar el portfolio: ${message}`);
  }
};

function emptyResult(loadError: string): {
  summary: PortfolioSummaryOut | null;
  positions: PositionOut[];
  equity_series: EquitySnapshotOut[];
  loadError: string;
} {
  return {
    summary: null,
    positions: [],
    equity_series: [],
    loadError,
  };
}
