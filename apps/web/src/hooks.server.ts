import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';

/**
 * Cookie hook — gates the `(app)` route group.
 *
 * Per spec scenario "Authenticated request to (app) route": on every
 * request to a route inside `(app)`, fetch FastAPI `/api/v1/auth/me`
 * with the user's session cookie. On 200 → stash the user on
 * `event.locals.user` and proceed; on 401 → 302 to
 * `/login?redirect_to=<originating-path>`.
 *
 * The `(auth)/login/` route is OUTSIDE the gated group so it can render
 * for unauthenticated users; the root `/` is also ungated for now (slice
 * W1 will mount the dashboard there and bring it under `(app)`).
 */
export const handle: Handle = async ({ event, resolve }) => {
  event.locals.user = null;

  const isGatedRoute = event.route.id?.startsWith('/(app)') ?? false;
  if (!isGatedRoute) {
    return resolve(event);
  }

  const sessionCookie = event.cookies.get(COOKIE_NAME);
  const meResponse = sessionCookie
    ? await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
        headers: { Cookie: `${COOKIE_NAME}=${sessionCookie}` }
      }).catch(() => null)
    : null;

  if (!meResponse || meResponse.status !== 200) {
    const originating = event.url.pathname + event.url.search;
    const target = `/login?redirect_to=${encodeURIComponent(originating)}`;
    throw redirect(302, target);
  }

  const userPayload = (await meResponse.json()) as App.Locals['user'];
  event.locals.user = userPayload;

  return resolve(event);
};
