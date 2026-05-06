/**
 * Research brief detail loader — slice R5 (research-brief-synthesis).
 *
 * Fetches the latest brief + recent facts for `[symbol]`. Both endpoints
 * exist as full implementations from R5 (replaces R1 stubs). The
 * response shape consumed here is the extended `BriefResponse` from
 * `packages/shared-types/src/index.ts` (typegen regenerates after R5
 * lands the OpenAPI surface).
 */

import { error } from '@sveltejs/kit';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch }) => {
  const symbol = params.symbol.toUpperCase();
  // Parallel fetches — both endpoints are slim.
  const [briefRes, factsRes] = await Promise.all([
    fetch(`/api/v1/research/briefs/${encodeURIComponent(symbol)}`),
    fetch(`/api/v1/research/facts/${encodeURIComponent(symbol)}`)
  ]);

  // 404 / 501: surface as "no brief yet" rather than blowing up the page.
  let brief: unknown = null;
  if (briefRes.ok) {
    brief = await briefRes.json();
  } else if (briefRes.status !== 404 && briefRes.status !== 501) {
    throw error(briefRes.status, `Failed to load brief: ${briefRes.statusText}`);
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
    facts
  };
};
