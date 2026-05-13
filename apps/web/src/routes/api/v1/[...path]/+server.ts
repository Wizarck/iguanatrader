/**
 * Catch-all API proxy.
 *
 * Browser-side `fetch('/api/v1/...')` from inside `(app)` pages targets
 * the SvelteKit origin, which has no native API routes. This handler
 * forwards every method to the FastAPI container behind `API_BASE_URL`,
 * propagating the session cookie so the auth middleware accepts the
 * call, and streaming the response (status, headers, body) back to the
 * browser.
 *
 * Server-side `load` fns and form actions should still hit
 * `${API_BASE_URL}/api/v1/...` directly — one fewer hop and no need
 * for this proxy.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';

import type { RequestHandler } from './$types';

const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'transfer-encoding',
  'te',
  'trailer',
  'upgrade',
  'proxy-authorization',
  'proxy-authenticate',
  'host',
  'content-length'
]);

const proxy: RequestHandler = async ({ params, request, url, cookies }) => {
  const upstreamUrl = `${API_BASE_URL}/api/v1/${params.path}${url.search}`;

  const headers = new Headers();
  for (const [k, v] of request.headers) {
    if (!HOP_BY_HOP.has(k.toLowerCase())) headers.set(k, v);
  }
  const session = cookies.get(COOKIE_NAME);
  if (session) headers.set('cookie', `${COOKIE_NAME}=${session}`);

  const init: RequestInit = {
    method: request.method,
    headers,
    redirect: 'manual'
  };
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = await request.arrayBuffer();
  }

  const upstream = await fetch(upstreamUrl, init);

  const respHeaders = new Headers();
  for (const [k, v] of upstream.headers) {
    if (!HOP_BY_HOP.has(k.toLowerCase())) respHeaders.set(k, v);
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: respHeaders
  });
};

export const GET: RequestHandler = proxy;
export const POST: RequestHandler = proxy;
export const PUT: RequestHandler = proxy;
export const PATCH: RequestHandler = proxy;
export const DELETE: RequestHandler = proxy;
export const OPTIONS: RequestHandler = proxy;
