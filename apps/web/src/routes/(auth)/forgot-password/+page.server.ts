import { fail, type Actions } from '@sveltejs/kit';

import { API_BASE_URL } from '$lib/config';

/**
 * Forgot-password form action — proxies to FastAPI's
 * `POST /api/v1/auth/forgot-password`.
 *
 * The endpoint is anti-enumeration: a known and an unknown email both
 * return 200 with the same generic body. This form action therefore
 * surfaces a SINGLE success view regardless of whether the email
 * matched anything on the backend; the UI MUST NOT branch on the
 * email's existence (defeating enumeration is a SvelteKit-level
 * concern too).
 *
 * Per spec scenarios:
 *
 * * On 200 → return `{ submitted: true, message }` so the page
 *   renders the generic confirmation block.
 * * On 429 → `fail(429, { alert_variant: 'destructive', message, retry_after })`.
 * * On 422 (Pydantic email validation) → `fail(400, { alert_variant: 'destructive', ... })`.
 * * On 5xx / network → `fail(...)` with a degraded message; the user
 *   can retry shortly.
 */
export const actions: Actions = {
  default: async ({ request, fetch }) => {
    const formData = await request.formData();
    const email = String(formData.get('email') ?? '').trim();

    if (!email) {
      return fail(400, {
        alert_variant: 'destructive' as const,
        message: 'Introduce un email para continuar.'
      });
    }

    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/v1/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
    } catch {
      return fail(502, {
        alert_variant: 'destructive' as const,
        message: 'Backend unreachable. Try again shortly.'
      });
    }

    if (response.status === 200) {
      let message =
        'Si la dirección está registrada, recibirás instrucciones por email, Telegram o WhatsApp en los próximos minutos.';
      try {
        const body = (await response.json()) as { message?: string };
        if (typeof body.message === 'string' && body.message.length > 0) {
          message = body.message;
        }
      } catch {
        // Body unparseable — keep the default message.
      }
      return {
        submitted: true,
        message
      };
    }

    if (response.status === 429) {
      const retryAfter = parseRetryAfter(response);
      return fail(429, {
        alert_variant: 'destructive' as const,
        message: `Demasiados intentos. Espera ${retryAfter}s antes de reintentar.`,
        retry_after: retryAfter
      });
    }

    if (response.status === 422 || response.status === 400) {
      return fail(400, {
        alert_variant: 'destructive' as const,
        message: 'Email con formato inválido.'
      });
    }

    return fail(response.status, {
      alert_variant: 'destructive' as const,
      message: `Unexpected error (${response.status}). Try again.`
    });
  }
};

function parseRetryAfter(response: Response): number {
  const header = response.headers.get('retry-after');
  if (header && /^\d+$/.test(header)) {
    return parseInt(header, 10);
  }
  return 3600;
}
