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
 *
 * Slice `auth-change-password`: when `/auth/me` reports
 * `must_change_password=true`, redirect every `(app)` route (except the
 * change-password page itself) to `/account/change-password?required=1`.
 * The API-side middleware enforces the same gate for non-browser API
 * consumers; this hook is the browser UX layer.
 */
const PASSWORD_CHANGE_PATH = '/account/change-password';

export const handle: Handle = async ({ event, resolve }) => {
  event.locals.user = null;

  const isGatedRoute = event.route.id?.startsWith('/(app)') ?? false;
  if (!isGatedRoute) {
    return resolve(event);
  }

  const sessionCookie = event.cookies.get(COOKIE_NAME);
  const meResponse = sessionCookie
    ? await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
        headers: { Cookie: `${COOKIE_NAME}=${sessionCookie}` },
      }).catch(() => null)
    : null;

  if (!meResponse || meResponse.status !== 200) {
    const originating = event.url.pathname + event.url.search;
    const target = `/login?redirect_to=${encodeURIComponent(originating)}`;
    throw redirect(302, target);
  }

  const userPayload = (await meResponse.json()) as App.Locals['user'];
  event.locals.user = userPayload;

  // Slice `auth-change-password` gate: route browsers away from any
  // `(app)` route until the password is rotated, EXCEPT the
  // change-password page itself (otherwise we'd loop). The path check
  // uses `startsWith` so any future child route under
  // `/account/change-password/` (eg. a success splash) is also exempt.
  if (
    userPayload?.must_change_password &&
    !event.url.pathname.startsWith(PASSWORD_CHANGE_PATH)
  ) {
    throw redirect(302, `${PASSWORD_CHANGE_PATH}?required=1`);
  }

  return resolve(event);
};
