import { fail, redirect, type Actions } from '@sveltejs/kit';

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import type { PageServerLoad } from './$types';

/**
 * Change-password form action (slice `auth-change-password`).
 *
 * Mirrors the slice-4 login form action pattern: posts JSON to FastAPI
 * `POST /api/v1/auth/change-password` with the session cookie, then
 * routes the user based on the response.
 *
 * Per slice proposal §UI:
 *
 * * `?required=1` query → render the "you must change your password"
 *   banner. The load function surfaces this to the page.
 * * Client-side "new vs confirm" mismatch → `fail(400)` BEFORE the API
 *   call (cheap UX; the API doesn't see the confirm field).
 * * API 204 → `redirect(303, '/portfolio')` (the slice-4 default
 *   post-auth landing route).
 * * API 401 (`auth-mismatch`) → `fail(401)` with copy specific to the
 *   "current password is wrong" branch.
 * * API 400 (`validation`) → `fail(400)` surfacing the API's `detail`.
 * * Anything else → `fail(<status>)` with a generic error.
 */
export const load: PageServerLoad = async ({ url }) => {
  return {
    required: url.searchParams.get('required') === '1',
  };
};

export const actions: Actions = {
  default: async ({ request, fetch, cookies }) => {
    const formData = await request.formData();
    const oldPassword = String(formData.get('old_password') ?? '');
    const newPassword = String(formData.get('new_password') ?? '');
    const confirmPassword = String(formData.get('confirm') ?? '');

    if (!oldPassword || !newPassword || !confirmPassword) {
      return fail(400, {
        alert_variant: 'destructive' as const,
        message: 'All fields are required.',
      });
    }

    if (newPassword !== confirmPassword) {
      return fail(400, {
        alert_variant: 'destructive' as const,
        message: 'New password and confirmation do not match.',
      });
    }

    const sessionCookie = cookies.get(COOKIE_NAME);
    if (!sessionCookie) {
      // The hook should have redirected to /login already, but guard
      // defensively in case the cookie was cleared mid-request.
      throw redirect(303, '/login');
    }

    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/v1/auth/change-password`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Cookie: `${COOKIE_NAME}=${sessionCookie}`,
        },
        body: JSON.stringify({
          old_password: oldPassword,
          new_password: newPassword,
        }),
      });
    } catch {
      return fail(502, {
        alert_variant: 'destructive' as const,
        message: 'Backend unreachable. Try again shortly.',
      });
    }

    if (response.status === 204) {
      throw redirect(303, '/portfolio');
    }

    if (response.status === 401) {
      return fail(401, {
        alert_variant: 'destructive' as const,
        message: 'Current password is incorrect.',
      });
    }

    if (response.status === 400) {
      let detail = 'New password did not pass validation.';
      try {
        const body = (await response.json()) as { detail?: string };
        if (typeof body.detail === 'string') detail = body.detail;
      } catch {
        // ignore — fall through with the default detail.
      }
      return fail(400, {
        alert_variant: 'destructive' as const,
        message: detail,
      });
    }

    return fail(response.status, {
      alert_variant: 'destructive' as const,
      message: `Unexpected error (${response.status}). Try again.`,
    });
  },
};
