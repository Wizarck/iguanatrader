/**
 * `useFetch` composable — slice W1.
 *
 * Thin wrapper over native `fetch` that:
 *
 * - Always sets `credentials: 'include'` so the session cookie travels
 *   on every request (the FastAPI cookie hook depends on it).
 * - Always sets `Accept: application/json, application/problem+json`.
 * - On 4xx/5xx responses with `Content-Type: application/problem+json`,
 *   parses the body as `Problem` and **returns** it (does NOT throw) —
 *   the caller pattern-matches:
 *
 *   ```ts
 *   const result = await useFetch<Trade[]>('/api/v1/trades');
 *   if ('type' in result && result.type.startsWith('urn:iguanatrader:')) {
 *     // Problem response — render error UI.
 *   } else {
 *     // Trade[] — render success UI.
 *   }
 *   ```
 *
 * - On non-Problem error responses or transport errors (network
 *   failure, malformed JSON), throws.
 *
 * Per design D5. Backend retries are caller-side (each domain page
 * decides idempotency), per slice 5 D5 open question.
 */

import type { Problem } from '$lib/types/problem';

import { API_BASE_URL } from '$lib/config';

/**
 * Result discriminator helper — caller can use this to narrow.
 *
 * ```ts
 * const r = await useFetch<Trade[]>('/api/v1/trades');
 * if (isProblem(r)) { ... }
 * ```
 */
export function isProblem(value: unknown): value is Problem {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return (
    typeof obj.type === 'string' && typeof obj.title === 'string' && typeof obj.status === 'number'
  );
}

/**
 * Resolve a relative URL. Absolute URLs pass through.
 *
 * In the BROWSER we deliberately resolve to a SAME-ORIGIN path (empty base)
 * so the request goes through the SvelteKit `/api/v1/[...path]` proxy, which
 * forwards the session cookie to the API (see that route's docstring). Only on
 * the SERVER (SSR `load` / form actions, where `window` is undefined) do we hit
 * `API_BASE_URL` directly. Resolving against `API_BASE_URL` in the browser sent
 * the request to the bundle-inlined default (`http://127.0.0.1:8000`, the
 * user's own loopback), bypassing the proxy → 401 → the daemon-status poll and
 * SSE never connected (the "…" pills).
 */
function resolveUrl(url: string): string {
  if (/^https?:\/\//.test(url)) return url;
  const base = typeof window === 'undefined' ? API_BASE_URL : '';
  if (url.startsWith('/')) return `${base}${url}`;
  return `${base}/${url}`;
}

export async function useFetch<TResponse>(
  url: string,
  init: RequestInit = {},
): Promise<TResponse | Problem> {
  const resolvedUrl = resolveUrl(url);

  const headers = new Headers(init.headers);
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json, application/problem+json');
  }
  // Only set Content-Type on non-GET requests with a body.
  const method = (init.method ?? 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD' && init.body != null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(resolvedUrl, {
    ...init,
    headers,
    credentials: init.credentials ?? 'include',
  });

  const contentType = response.headers.get('content-type') ?? '';

  // Problem branch — 4xx/5xx with problem+json.
  if (!response.ok && contentType.toLowerCase().includes('application/problem+json')) {
    return (await response.json()) as Problem;
  }

  // Non-OK without problem+json → throw with a synthesised message.
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(
      `useFetch: ${method} ${resolvedUrl} failed with ${response.status}` +
        (text ? `: ${text.slice(0, 200)}` : ''),
    );
  }

  // 204 No Content → return null cast (caller decides shape).
  if (response.status === 204) {
    return null as unknown as TResponse;
  }

  // Default success path: parse JSON.
  if (contentType.toLowerCase().includes('application/json')) {
    return (await response.json()) as TResponse;
  }

  // Caller expected JSON but the server returned something else; treat
  // as a transport error so the surrounding try/catch surfaces it.
  throw new Error(`useFetch: ${method} ${resolvedUrl} returned non-JSON body (${contentType})`);
}
