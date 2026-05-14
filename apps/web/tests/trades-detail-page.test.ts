/**
 * Trade detail page tests (slice trades-list-and-detail).
 *
 * Covers the `[id]/+page.server.ts` load fn end-to-end with mocked
 * fetch on both upstream calls (`/trades/{id}` + `/trades/{id}/fills`):
 *
 *   1. Happy path — trade + fills propagate.
 *   2. No fills (200 with empty list) — `data.fills` is empty.
 *   3. API 503 on the trade call — `loadError` populated.
 *   4. API 503 on the fills call — `loadError` populated.
 *   5. Network throw — `loadError` populated.
 */

import { describe, expect, it, vi } from 'vitest';

import type { FillListOut, TradeOut } from '../src/lib/trades/types';

async function importLoad() {
  const mod = await import('../src/routes/(app)/trades/[id]/+page.server');
  return mod.load;
}

function buildEvent(params: { id: string }) {
  return {
    fetch: (...args: Parameters<typeof fetch>) => globalThis.fetch(...args),
    cookies: {
      get: (_name: string) => 'jwt-blob'
    },
    params
  };
}

const TRADE_ID = '00000000-0000-0000-0000-000000000001';

const SAMPLE_TRADE: TradeOut = {
  id: TRADE_ID,
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
};

const SAMPLE_FILLS: FillListOut = {
  items: [
    {
      id: '00000000-0000-0000-0000-0000000000f1',
      tenant_id: '00000000-0000-0000-0000-0000000000aa',
      order_id: '00000000-0000-0000-0000-0000000000d1',
      quantity_filled: '10',
      fill_price: '100.50',
      commission: '0.01',
      commission_currency: 'USD',
      filled_at: '2026-05-01T10:01:00Z',
      broker_fill_id: 'FILL-1',
      created_at: '2026-05-01T10:01:00Z'
    }
  ],
  total: 1,
  next_cursor: null
};

function fetchPair(opts: {
  tradeStatus?: number;
  fillsStatus?: number;
  tradeBody?: unknown;
  fillsBody?: unknown;
}) {
  return vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(async (input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.endsWith('/fills')) {
        return new Response(JSON.stringify(opts.fillsBody ?? {}), {
          status: opts.fillsStatus ?? 200,
          statusText: opts.fillsStatus && opts.fillsStatus >= 400 ? 'err' : 'OK',
          headers: { 'content-type': 'application/json' }
        });
      }
      return new Response(JSON.stringify(opts.tradeBody ?? {}), {
        status: opts.tradeStatus ?? 200,
        statusText: opts.tradeStatus && opts.tradeStatus >= 400 ? 'err' : 'OK',
        headers: { 'content-type': 'application/json' }
      });
    });
}

describe('trade detail page load()', () => {
  it('returns trade + fills on happy path', async () => {
    const load = await importLoad();
    const fetchSpy = fetchPair({
      tradeBody: SAMPLE_TRADE,
      fillsBody: SAMPLE_FILLS
    });

    const event = buildEvent({ id: TRADE_ID });
    const result = (await load(event as never)) as {
      trade: TradeOut | null;
      fills: FillListOut['items'];
      loadError: string | null;
    };

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(result.trade?.id).toBe(TRADE_ID);
    expect(result.fills).toHaveLength(1);
    expect(result.loadError).toBeNull();

    fetchSpy.mockRestore();
  });

  it('returns empty fills when backend reports no fills', async () => {
    const load = await importLoad();
    const fetchSpy = fetchPair({
      tradeBody: SAMPLE_TRADE,
      fillsBody: { items: [], total: 0, next_cursor: null }
    });

    const event = buildEvent({ id: TRADE_ID });
    const result = (await load(event as never)) as {
      trade: TradeOut | null;
      fills: FillListOut['items'];
      loadError: string | null;
    };

    expect(result.trade?.id).toBe(TRADE_ID);
    expect(result.fills).toEqual([]);
    expect(result.loadError).toBeNull();

    fetchSpy.mockRestore();
  });

  it('populates loadError when the trade call returns 503', async () => {
    const load = await importLoad();
    const fetchSpy = fetchPair({
      tradeStatus: 503,
      fillsBody: SAMPLE_FILLS
    });

    const event = buildEvent({ id: TRADE_ID });
    const result = (await load(event as never)) as {
      trade: TradeOut | null;
      loadError: string | null;
    };

    expect(result.trade).toBeNull();
    expect(result.loadError).toContain('503');

    fetchSpy.mockRestore();
  });

  it('populates loadError when the fills call returns 503', async () => {
    const load = await importLoad();
    const fetchSpy = fetchPair({
      tradeBody: SAMPLE_TRADE,
      fillsStatus: 503
    });

    const event = buildEvent({ id: TRADE_ID });
    const result = (await load(event as never)) as {
      trade: TradeOut | null;
      loadError: string | null;
    };

    expect(result.trade).toBeNull();
    expect(result.loadError).toContain('503');

    fetchSpy.mockRestore();
  });

  it('populates loadError on network throw', async () => {
    const load = await importLoad();
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValue(new Error('ECONNREFUSED'));

    const event = buildEvent({ id: TRADE_ID });
    const result = (await load(event as never)) as {
      trade: TradeOut | null;
      loadError: string | null;
    };

    expect(result.trade).toBeNull();
    expect(result.loadError).toContain('ECONNREFUSED');

    fetchSpy.mockRestore();
  });
});
