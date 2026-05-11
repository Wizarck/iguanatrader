/**
 * Audit-trail detail loader — slice research-frontend-extras-2.
 *
 * Fetches the current brief + recent facts for `[symbol]` and validates
 * `[brief_version]` against the brief's version. On mismatch redirects to
 * the canonical URL so deep links coming from older snapshots gracefully
 * land on the current version's trail.
 *
 * Future-proofing: when `/briefs/{symbol}/versions/{n}` lands, swap the
 * fetch to honour the URL parameter directly without touching this loader.
 */

import { error, redirect } from '@sveltejs/kit';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch }) => {
  const symbol = params.symbol.toUpperCase();
  const requestedVersion = Number.parseInt(params.brief_version, 10);
  if (!Number.isFinite(requestedVersion) || requestedVersion < 0) {
    throw error(400, `Invalid brief_version: ${params.brief_version}`);
  }

  const [briefRes, factsRes] = await Promise.all([
    fetch(`/api/v1/research/briefs/${encodeURIComponent(symbol)}`),
    fetch(`/api/v1/research/facts/${encodeURIComponent(symbol)}`)
  ]);

  if (!briefRes.ok) {
    if (briefRes.status === 404 || briefRes.status === 501) {
      throw error(404, `No brief available for ${symbol}`);
    }
    throw error(briefRes.status, `Failed to load brief: ${briefRes.statusText}`);
  }
  const brief = (await briefRes.json()) as Record<string, unknown>;
  const currentVersion = Number(brief?.version ?? 0);
  if (currentVersion !== requestedVersion) {
    throw redirect(302, `/research/${encodeURIComponent(symbol)}/audit-trail/${currentVersion}`);
  }

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
