/**
 * Approvals dashboard page loader + actions (slice approvals-dashboard-ui).
 *
 * Wires the `/approvals` tab to the 3 endpoints shipped by slice P1
 * (`approval-channels-multichannel`):
 *
 *   - `load`     → `GET  /api/v1/approvals`               (pending list)
 *   - `approve`  → `POST /api/v1/approvals/{id}/approve`  (empty body)
 *   - `reject`   → `POST /api/v1/approvals/{id}/reject`   (body { reason })
 *
 * Same cookie-forwarding + `fail`/`redirect` pattern as
 * `(app)/strategies/[symbol]/+page.server.ts` (PR #145). The dashboard
 * intentionally does NOT pass `decided_via_channel` — the backend
 * infers it server-side from the route handler.
 */

import { fail, redirect, type Actions } from '@sveltejs/kit';

import type { ApprovalRequest } from '$lib/approvals/types';
import { API_BASE_URL, COOKIE_NAME } from '$lib/config';

import type { PageServerLoad } from './$types';

type LoadResult = {
  approvals: ApprovalRequest[];
  loadError: string | null;
};

export const load: PageServerLoad = async ({ fetch, cookies }): Promise<LoadResult> => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/approvals`, {
      headers: sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : {},
    });
    if (!res.ok) {
      return {
        approvals: [],
        loadError: `No se pudieron cargar las aprobaciones: ${res.status} ${res.statusText}`,
      };
    }
    const approvals = (await res.json()) as ApprovalRequest[];
    return { approvals, loadError: null };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      approvals: [],
      loadError: `No se pudieron cargar las aprobaciones: ${message}`,
    };
  }
};

function isValidRequestId(value: string): boolean {
  // Loose UUID check — backend revalidates. We only guard against empty
  // strings and obvious garbage so we don't fire a request we know will
  // 404 on the API side.
  return /^[0-9a-fA-F-]{8,}$/.test(value);
}

export const actions: Actions = {
  approve: async ({ request, fetch, cookies }) => {
    const formData = await request.formData();
    const requestId = String(formData.get('request_id') ?? '').trim();

    if (!requestId || !isValidRequestId(requestId)) {
      return fail(400, { formError: 'Invalid request_id.' });
    }

    const sessionCookie = cookies.get(COOKIE_NAME);
    const url = `${API_BASE_URL}/api/v1/approvals/${encodeURIComponent(requestId)}/approve`;
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : {}),
        },
        body: '',
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return fail(502, { formError: `Backend unreachable: ${message}` });
    }

    if (response.status >= 200 && response.status < 300) {
      throw redirect(303, '/approvals');
    }

    let detail = `Error ${response.status} approving request.`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // ignore — fall through with default detail.
    }
    return fail(response.status, { formError: detail });
  },

  reject: async ({ request, fetch, cookies }) => {
    const formData = await request.formData();
    const requestId = String(formData.get('request_id') ?? '').trim();
    const reasonRaw = formData.get('reason');
    const reason =
      typeof reasonRaw === 'string' && reasonRaw.trim().length > 0
        ? reasonRaw.trim()
        : null;

    if (!requestId || !isValidRequestId(requestId)) {
      return fail(400, { formError: 'Invalid request_id.' });
    }

    const sessionCookie = cookies.get(COOKIE_NAME);
    const url = `${API_BASE_URL}/api/v1/approvals/${encodeURIComponent(requestId)}/reject`;
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : {}),
        },
        body: JSON.stringify({ reason }),
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return fail(502, { formError: `Backend unreachable: ${message}` });
    }

    if (response.status >= 200 && response.status < 300) {
      throw redirect(303, '/approvals');
    }

    let detail = `Error ${response.status} rejecting request.`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // ignore — fall through with default detail.
    }
    return fail(response.status, { formError: detail });
  },
};
