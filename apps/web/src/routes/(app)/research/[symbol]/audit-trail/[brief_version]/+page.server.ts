/**
 * Audit-trail detail loader — slice research-frontend-extras-2 +
 * research-brief-by-version-endpoint.
 *
 * Fetches the brief at the requested `[brief_version]` via
 * `/api/v1/research/briefs/{symbol}/versions/{version}` (load-bearing —
 * not decorative). 404 surfaces as SvelteKit `error(404, ...)` so deep
 * links to non-existent versions yield a clean error page instead of
 * a silent redirect to current.
 */

import { error } from '@sveltejs/kit';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch }) => {
  const symbol = params.symbol.toUpperCase();
  const requestedVersion = Number.parseInt(params.brief_version, 10);
  if (!Number.isFinite(requestedVersion) || requestedVersion < 0) {
    throw error(400, `Invalid brief_version: ${params.brief_version}`);
  }

  const [briefRes, factsRes] = await Promise.all([
    fetch(
      `/api/v1/research/briefs/${encodeURIComponent(symbol)}/versions/${requestedVersion}`
    ),
    fetch(`/api/v1/research/facts/${encodeURIComponent(symbol)}`)
  ]);

  if (!briefRes.ok) {
    if (briefRes.status === 404) {
      throw error(404, `No brief at version ${requestedVersion} for ${symbol}`);
    }
    throw error(briefRes.status, `Failed to load brief: ${briefRes.statusText}`);
  }
  const brief = (await briefRes.json()) as Record<string, unknown>;

  let facts: unknown[] = [];
  if (factsRes.ok) {
    facts = await factsRes.json();
  } else if (factsRes.status !== 404) {
    throw error(factsRes.status, `Failed to load facts: ${factsRes.statusText}`);
  }

  return {
    symbol,
    brief,
    facts,
    requestedVersion
  };
};
