/**
 * Strategies list page tests (slice strategies-config-ui).
 *
 * Covers the `+page.server.ts` load fn end-to-end with mocked fetch
 * against `GET /api/v1/strategies`:
 *
 *   1. Happy path — items propagate as `data.strategies` + total carries.
 *   2. Empty list — `data.strategies` is empty + no loadError.
 *   3. API 503 — `loadError` populated, page does not crash.
 *   4. API 401 — `loadError` populated with the upstream status.
 *   5. Network throw — `loadError` populated with the error message.
 */

import { describe, expect, it, vi } from 'vitest';

import type {
  StrategyConfigListOut,
  StrategyConfigOut,
} from '../src/lib/strategies/types';

async function importLoad() {
  const mod = await import('../src/routes/(app)/strategies/+page.server');
  return mod.load;
}

function buildEvent(opts?: { cookieValue?: string }) {
  const cookies = new Map<string, string>();
  if (opts?.cookieValue) cookies.set('iguana_session', opts.cookieValue);
  return {
    fetch: (...args: Parameters<typeof fetch>) => globalThis.fetch(...args),
    cookies: {
      get: (name: string) => cookies.get(name) ?? null,
    },
  };
}

const TENANT_ID = '00000000-0000-0000-0000-0000000000aa';

const SAMPLE_STRATEGY: StrategyConfigOut = {
  id: '00000000-0000-0000-0000-000000000001',
  tenant_id: TENANT_ID,
  strategy_kind: 'donchian_atr',
  symbol: 'SPY',
  params: { lookback: 20, atr_mult: 2.0 },
  enabled: true,
  version: 3,
  created_at: '2026-05-01T10:00:00Z',
  updated_at: '2026-05-13T09:00:00Z',
};

const SAMPLE_DISABLED: StrategyConfigOut = {
  ...SAMPLE_STRATEGY,
  id: '00000000-0000-0000-0000-000000000002',
  symbol: 'AAPL',
  strategy_kind: 'sma_cross',
  params: { fast: 50, slow: 200 },
  enabled: false,
  version: 1,
};

const SAMPLE_LIST: StrategyConfigListOut = {
  items: [SAMPLE_STRATEGY, SAMPLE_DISABLED],
  total: 2,
};

type LoadResult = {
  strategies: StrategyConfigOut[];
  total: number;
  loadError: string | null;
};

describe('strategies list page load()', () => {
  it('returns items + total on 200', async () => {
    const load = await importLoad();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_LIST), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const event = buildEvent({ cookieValue: 'jwt-blob' });
    const result = (await load(event as never)) as LoadResult;

    expect(fetchSpy).toHaveBeenCalledOnce();
    const calledUrl = fetchSpy.mock.calls[0][0] as string;
    expect(calledUrl).toContain('/api/v1/strategies');
    const callInit = fetchSpy.mock.calls[0][1] as RequestInit | undefined;
    expect((callInit?.headers as Record<string, string>).Cookie).toContain('jwt-blob');
    expect(result.strategies).toHaveLength(2);
    expect(result.strategies[0].symbol).toBe('SPY');
    expect(result.strategies[1].enabled).toBe(false);
    expect(result.total).toBe(2);
    expect(result.loadError).toBeNull();

    fetchSpy.mockRestore();
  });

  it('returns empty list when backend reports no items', async () => {
    const load = await importLoad();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.strategies).toEqual([]);
    expect(result.total).toBe(0);
    expect(result.loadError).toBeNull();

    fetchSpy.mockRestore();
  });

  it('populates loadError on 503', async () => {
    const load = await importLoad();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('', {
        status: 503,
        statusText: 'Service Unavailable',
      }),
    );

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.strategies).toEqual([]);
    expect(result.loadError).toContain('503');

    fetchSpy.mockRestore();
  });

  it('populates loadError on 401', async () => {
    const load = await importLoad();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('', {
        status: 401,
        statusText: 'Unauthorized',
      }),
    );

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.strategies).toEqual([]);
    expect(result.loadError).toContain('401');

    fetchSpy.mockRestore();
  });

  it('populates loadError on network throw', async () => {
    const load = await importLoad();
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValue(new Error('ECONNREFUSED'));

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.strategies).toEqual([]);
    expect(result.loadError).toContain('ECONNREFUSED');

    fetchSpy.mockRestore();
  });
});
