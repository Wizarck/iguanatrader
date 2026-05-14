/**
 * Trades list page tests (slice trades-list-and-detail).
 *
 * Covers the `+page.server.ts` load fn end-to-end with mocked fetch:
 *
 *   1. Happy path — items propagate as `data.trades`.
 *   2. Empty list — `data.trades` is empty + no loadError.
 *   3. API 503 — `loadError` populated, page does not crash.
 *   4. Network throw — `loadError` populated with the error message.
 *   5. Side badge variant mapping (`buy` → success, `sell` → destructive).
 *   6. State badge variant mapping (`open` → accent, others → mute).
 */

import { describe, expect, it, vi } from 'vitest';

import { sideVariant, stateVariant } from '../src/lib/trades/variants';
import type { TradeListOut } from '../src/lib/trades/types';

async function importLoad() {
  const mod = await import('../src/routes/(app)/trades/+page.server');
  return mod.load;
}

function buildEvent(opts?: { cookieValue?: string }) {
  const cookies = new Map<string, string>();
  if (opts?.cookieValue) cookies.set('iguana_session', opts.cookieValue);
  return {
    fetch: (...args: Parameters<typeof fetch>) => globalThis.fetch(...args),
    cookies: {
      get: (name: string) => cookies.get(name) ?? null
    }
  };
}

const SAMPLE_TRADES: TradeListOut = {
  items: [
    {
      id: '00000000-0000-0000-0000-000000000001',
      tenant_id: '00000000-0000-0000-0000-0000000000aa',
      proposal_id: '00000000-0000-0000-0000-0000000000bb',
      symbol: 'AAPL',
      side: 'buy',
      quantity: '10',
      mode: 'paper',
      state: 'open',
      opened_at: '2026-05-01T10:00:00Z',
      closed_at: null,
      created_at: '2026-05-01T10:00:00Z'
    },
    {
      id: '00000000-0000-0000-0000-000000000002',
      tenant_id: '00000000-0000-0000-0000-0000000000aa',
      proposal_id: '00000000-0000-0000-0000-0000000000cc',
      symbol: 'MSFT',
      side: 'sell',
      quantity: '5',
      mode: 'paper',
      state: 'closed',
      opened_at: '2026-05-01T09:00:00Z',
      closed_at: '2026-05-01T15:00:00Z',
      created_at: '2026-05-01T09:00:00Z'
    }
  ],
  total: 2,
  next_cursor: null
};

describe('trades list page load()', () => {
  it('returns trades array + total on 200', async () => {
    const load = await importLoad();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_TRADES), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      })
    );

    const event = buildEvent({ cookieValue: 'jwt-blob' });
    const result = (await load(event as never)) as {
      trades: typeof SAMPLE_TRADES.items;
      total: number;
      loadError: string | null;
    };

    expect(fetchSpy).toHaveBeenCalledOnce();
    const calledUrl = fetchSpy.mock.calls[0][0] as string;
    expect(calledUrl).toContain('/api/v1/trades');
    expect(result.trades).toHaveLength(2);
    expect(result.total).toBe(2);
    expect(result.loadError).toBeNull();

    fetchSpy.mockRestore();
  });

  it('returns empty trades list when backend returns no items', async () => {
    const load = await importLoad();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, next_cursor: null }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      })
    );

    const event = buildEvent();
    const result = (await load(event as never)) as {
      trades: unknown[];
      total: number;
      loadError: string | null;
    };

    expect(result.trades).toEqual([]);
    expect(result.total).toBe(0);
    expect(result.loadError).toBeNull();

    fetchSpy.mockRestore();
  });

  it('populates loadError on 503', async () => {
    const load = await importLoad();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{}', { status: 503, statusText: 'Service Unavailable' })
    );

    const event = buildEvent();
    const result = (await load(event as never)) as {
      trades: unknown[];
      loadError: string | null;
    };

    expect(result.trades).toEqual([]);
    expect(result.loadError).toContain('503');

    fetchSpy.mockRestore();
  });

  it('populates loadError on network throw', async () => {
    const load = await importLoad();
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValue(new Error('ECONNREFUSED'));

    const event = buildEvent();
    const result = (await load(event as never)) as {
      trades: unknown[];
      loadError: string | null;
    };

    expect(result.trades).toEqual([]);
    expect(result.loadError).toContain('ECONNREFUSED');

    fetchSpy.mockRestore();
  });
});

describe('side/state badge variant mapping', () => {
  it('maps buy → success, sell → destructive', () => {
    expect(sideVariant('buy')).toBe('success');
    expect(sideVariant('sell')).toBe('destructive');
  });

  it('maps open → accent, closed (and other) → mute', () => {
    expect(stateVariant('open')).toBe('accent');
    expect(stateVariant('closed')).toBe('mute');
    expect(stateVariant('cancelled')).toBe('mute');
  });
});
