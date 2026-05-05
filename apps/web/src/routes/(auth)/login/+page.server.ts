import { fail, redirect, type Actions, type Cookies } from '@sveltejs/kit';

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import { safeRedirectTo } from '$lib/redirect';

/**
 * Login form action — proxies to FastAPI's `POST /api/v1/auth/login`,
 * propagates the `Set-Cookie` to the user-agent at the SvelteKit
 * origin, and redirects to the allow-listed `redirect_to` (or `/`).
 *
 * Per design D8 + D9 (slice 4 `auth-jwt-cookie`):
 *
 * * The form is a server-side form action (NOT a client-side `fetch`)
 *   so the cookie originates at the SvelteKit host — defeats the
 *   SameSite=Strict third-party cookie issue + works without JS.
 * * `redirect_to` is allow-listed by :func:`safeRedirectTo` (single
 *   leading `/`, no `//`, no `://`, no `\`); anything else falls back
 *   to `/`.
 *
 * Per spec scenarios:
 *
 * * On 200 → propagate Set-Cookie + return `redirect(302, redirect_to)`.
 * * On 401 → `fail(401, { alert_variant: 'destructive', message: ... })`.
 * * On 429 → `fail(429, { ..., retry_after })` so the page can render a
 *   countdown.
 * * On 503 → `fail(503, { alert_variant: 'warn', message + detail })`.
 */
export const actions: Actions = {
  default: async ({ request, fetch, cookies, url }) => {
    const formData = await request.formData();
    const email = String(formData.get('email') ?? '').trim();
    const password = String(formData.get('password') ?? '');

    if (!email || !password) {
      return fail(400, {
        alert_variant: 'destructive' as const,
        message: 'Email and password are required.'
      });
    }

    const redirectTo = safeRedirectTo(url.searchParams.get('redirect_to'));

    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
    } catch {
      return fail(502, {
        alert_variant: 'destructive' as const,
        message: 'Backend unreachable. Try again shortly.'
      });
    }

    if (response.status === 200) {
      propagateSetCookie(response, cookies);
      throw redirect(302, redirectTo);
    }

    if (response.status === 401) {
      return fail(401, {
        alert_variant: 'destructive' as const,
        message: 'Invalid email or password.'
      });
    }

    if (response.status === 429) {
      const retryAfter = parseRetryAfter(response);
      return fail(429, {
        alert_variant: 'destructive' as const,
        message: `Rate limit reached. Wait ${retryAfter}s before retrying.`,
        retry_after: retryAfter
      });
    }

    if (response.status === 503) {
      let detail = 'Backend not yet bootstrapped.';
      try {
        const body = (await response.json()) as { detail?: string };
        if (typeof body.detail === 'string') detail = body.detail;
      } catch {
        // body is non-JSON or empty; fall through with the default detail.
      }
      return fail(503, {
        alert_variant: 'warn' as const,
        message: 'Service not bootstrapped',
        detail
      });
    }

    return fail(response.status, {
      alert_variant: 'destructive' as const,
      message: `Unexpected error (${response.status}). Try again.`
    });
  }
};

/**
 * Copy the `iguana_session` cookie from the FastAPI response onto the
 * SvelteKit response so it lands at the user-agent at the SvelteKit
 * origin. Other Set-Cookie headers are ignored — only the session
 * cookie is part of the auth contract.
 */
function propagateSetCookie(response: Response, cookies: Cookies): void {
  const rawCookieHeader = response.headers.get('set-cookie');
  if (!rawCookieHeader) return;

  // The header may carry a single cookie (FastAPI default) — parse
  // permissively. A more robust split would handle multiple cookies via
  // `Headers.getSetCookie()` (Node 18.14+); SvelteKit's adapter-node
  // exposes that, but for slice 4 the FastAPI side only sets one
  // cookie per response.
  const sessionMatch = rawCookieHeader.match(
    new RegExp(`${COOKIE_NAME}=([^;]+)`)
  );
  if (!sessionMatch) return;

  const value = sessionMatch[1];
  const maxAgeMatch = rawCookieHeader.match(/Max-Age=(\d+)/i);
  const maxAge = maxAgeMatch ? parseInt(maxAgeMatch[1], 10) : 7 * 24 * 60 * 60;
  const isSecure = /\bSecure\b/i.test(rawCookieHeader);

  cookies.set(COOKIE_NAME, value, {
    path: '/',
    httpOnly: true,
    secure: isSecure,
    sameSite: 'strict',
    maxAge
  });
}

function parseRetryAfter(response: Response): number {
  const header = response.headers.get('retry-after');
  if (header && /^\d+$/.test(header)) {
    return parseInt(header, 10);
  }
  return 60;
}
