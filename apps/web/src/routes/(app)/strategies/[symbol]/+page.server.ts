/**
 * Strategy edit/upsert form route (slice strategies-config-ui).
 *
 * Two-mode load:
 *   - `params.symbol === 'new'` → render the create form with no
 *     pre-fill. The symbol field is editable.
 *   - else → `GET /api/v1/strategies/{symbol}` to pre-fill an existing
 *     enabled config; 404 → `loadError`.
 *
 * Two actions:
 *   - `upsert` → `PUT /api/v1/strategies/{symbol}` with the form body.
 *     Validates `strategy_kind`, `symbol` pattern, and that `params` is
 *     valid JSON object before forwarding to the backend (the backend
 *     re-validates via Pydantic regardless).
 *   - `disable` → `DELETE /api/v1/strategies/{symbol}` (soft-disable).
 */

import { fail, redirect, type Actions } from '@sveltejs/kit';

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import {
  STRATEGY_KINDS,
  SYMBOL_PATTERN,
  type StrategyConfigOut,
  type StrategyKind,
} from '$lib/strategies/types';

import type { PageServerLoad } from './$types';

type LoadResult =
  | { mode: 'new'; strategy: null; loadError: null; symbolPrefill: string }
  | { mode: 'edit'; strategy: StrategyConfigOut; loadError: null; symbolPrefill: '' }
  | { mode: 'edit'; strategy: null; loadError: string; symbolPrefill: '' };

export const load: PageServerLoad = async ({
  fetch,
  cookies,
  params,
  url,
}): Promise<LoadResult> => {
  const sym = params.symbol;
  if (sym === 'new') {
    // Slice research-strategy-handoff: when the operator clicks
    // "Configure strategy" on a brief detail page, the navigation
    // includes ?symbol=<SYM> so the form lands pre-filled. Without
    // the query param the field is blank (legacy /strategies/new).
    const fromQuery = url.searchParams.get('symbol')?.trim() ?? '';
    const symbolPrefill = fromQuery && SYMBOL_PATTERN.test(fromQuery) ? fromQuery : '';
    return { mode: 'new', strategy: null, loadError: null, symbolPrefill };
  }

  const sessionCookie = cookies.get(COOKIE_NAME);
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/strategies/${encodeURIComponent(sym)}`, {
      headers: sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : {},
    });
    if (res.status === 404) {
      return {
        mode: 'edit',
        strategy: null,
        loadError: `No active strategy found for ${sym}.`,
        symbolPrefill: '',
      };
    }
    if (!res.ok) {
      return {
        mode: 'edit',
        strategy: null,
        loadError: `Failed to load strategy: ${res.status} ${res.statusText}`,
        symbolPrefill: '',
      };
    }
    const strategy = (await res.json()) as StrategyConfigOut;
    return { mode: 'edit', strategy, loadError: null, symbolPrefill: '' };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      mode: 'edit',
      strategy: null,
      loadError: `Failed to load strategy: ${message}`,
      symbolPrefill: '',
    };
  }
};

type FieldErrors = Partial<Record<'symbol' | 'strategy_kind' | 'params', string>>;

function isStrategyKind(value: string): value is StrategyKind {
  return (STRATEGY_KINDS as readonly string[]).includes(value);
}

export const actions: Actions = {
  upsert: async ({ request, fetch, cookies, params }) => {
    const formData = await request.formData();
    const mode = String(formData.get('mode') ?? 'edit');
    const symbolRaw = String(formData.get('symbol') ?? params.symbol ?? '').trim();
    const strategyKind = String(formData.get('strategy_kind') ?? '').trim();
    const paramsRaw = String(formData.get('params') ?? '').trim();
    const enabled = formData.get('enabled') === 'on' || formData.get('enabled') === 'true';

    const fieldErrors: FieldErrors = {};

    const targetSymbol = mode === 'new' ? symbolRaw : symbolRaw || String(params.symbol ?? '');
    if (!targetSymbol) {
      fieldErrors.symbol = 'Symbol is required.';
    } else if (!SYMBOL_PATTERN.test(targetSymbol)) {
      fieldErrors.symbol = 'Invalid symbol: use A-Z and 0-9, max 16 characters.';
    }

    if (!strategyKind || !isStrategyKind(strategyKind)) {
      fieldErrors.strategy_kind = `Invalid strategy kind. Allowed: ${STRATEGY_KINDS.join(', ')}.`;
    }

    let parsedParams: Record<string, unknown> = {};
    if (!paramsRaw) {
      fieldErrors.params = 'Params is required (JSON object).';
    } else {
      try {
        const parsed: unknown = JSON.parse(paramsRaw);
        if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
          fieldErrors.params = 'Params must be a JSON object.';
        } else {
          parsedParams = parsed as Record<string, unknown>;
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        fieldErrors.params = `Invalid JSON: ${message}`;
      }
    }

    if (Object.keys(fieldErrors).length > 0) {
      return fail(400, {
        formError: 'Check the highlighted fields.',
        fieldErrors,
        values: { symbol: symbolRaw, strategy_kind: strategyKind, params: paramsRaw, enabled },
      });
    }

    const sessionCookie = cookies.get(COOKIE_NAME);
    const url = `${API_BASE_URL}/api/v1/strategies/${encodeURIComponent(targetSymbol)}`;
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : {}),
        },
        body: JSON.stringify({
          strategy_kind: strategyKind,
          params: parsedParams,
          enabled,
        }),
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return fail(502, {
        formError: `Backend unreachable: ${message}`,
        fieldErrors: {},
        values: { symbol: symbolRaw, strategy_kind: strategyKind, params: paramsRaw, enabled },
      });
    }

    if (response.status >= 200 && response.status < 300) {
      throw redirect(303, '/strategies');
    }

    let detail = `Save failed: HTTP ${response.status}.`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // Ignore — fall through with default detail.
    }
    return fail(response.status, {
      formError: detail,
      fieldErrors: {},
      values: { symbol: symbolRaw, strategy_kind: strategyKind, params: paramsRaw, enabled },
    });
  },

  disable: async ({ fetch, cookies, params }) => {
    const sym = String(params.symbol ?? '');
    if (!sym || sym === 'new') {
      return fail(400, { disableError: 'Cannot disable a strategy without a symbol.' });
    }
    const sessionCookie = cookies.get(COOKIE_NAME);
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/v1/strategies/${encodeURIComponent(sym)}`, {
        method: 'DELETE',
        headers: sessionCookie ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` } : {},
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return fail(502, { disableError: `Backend unreachable: ${message}` });
    }

    if (response.status >= 200 && response.status < 300) {
      throw redirect(303, '/strategies');
    }

    return fail(response.status, {
      disableError: `Failed to disable ${sym}: ${response.status} ${response.statusText}`,
    });
  },
};
