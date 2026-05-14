/**
 * Costs dashboard page tests (slice costs-dashboard-ui).
 *
 * Covers `+page.server.ts` load fn end-to-end with mocked fetch over the
 * 3 upstream endpoints:
 *
 *   1. Happy path — summary + by-provider + per-trade propagate.
 *   2. Empty (`total_calls === 0`) → page renders `EmptyState`.
 *   3. API 503 on any of the 3 → `loadError` populated.
 *   4. `cost_per_trade_usd === null` → propagated; UI maps to "destructive".
 *   5. High cost-per-trade (>5 USD) → propagated; UI maps to "destructive".
 */

import { describe, expect, it, vi } from 'vitest';

import type {
  CostByProviderDTO,
  CostPerTradeDTO,
  CostSummaryDTO,
} from '../src/lib/costs/types';
import { costPerTradeColour } from '../src/lib/costs/format';

async function importLoad() {
  const mod = await import('../src/routes/(app)/costs/+page.server');
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
const PERIOD_START = '2026-05-01T00:00:00Z';
const PERIOD_END = '2026-05-31T23:59:59Z';

const SAMPLE_SUMMARY: CostSummaryDTO = {
  tenant_id: TENANT_ID,
  period_start: PERIOD_START,
  period_end: PERIOD_END,
  total_cost_usd: '12.45',
  total_calls: 320,
  cached_calls: 48,
};

const SAMPLE_BY_PROVIDER: CostByProviderDTO = {
  tenant_id: TENANT_ID,
  period_start: PERIOD_START,
  period_end: PERIOD_END,
  breakdown: [
    { provider: 'anthropic', cost_usd: '9.80', call_count: 240 },
    { provider: 'openai', cost_usd: '2.65', call_count: 80 },
  ],
};

const SAMPLE_PER_TRADE: CostPerTradeDTO = {
  tenant_id: TENANT_ID,
  period_start: PERIOD_START,
  period_end: PERIOD_END,
  total_llm_cost_usd: '12.45',
  closed_trades_count: 5,
  cost_per_trade_usd: '2.49',
};

type LoadResult = {
  summary: CostSummaryDTO | null;
  byProvider: CostByProviderDTO | null;
  perTrade: CostPerTradeDTO | null;
  loadError: string | null;
};

function mockTriple(opts: {
  summaryStatus?: number;
  byProviderStatus?: number;
  perTradeStatus?: number;
  summaryBody?: unknown;
  byProviderBody?: unknown;
  perTradeBody?: unknown;
}) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: string | URL | Request) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.includes('/costs/by-provider')) {
      return new Response(JSON.stringify(opts.byProviderBody ?? SAMPLE_BY_PROVIDER), {
        status: opts.byProviderStatus ?? 200,
        statusText: opts.byProviderStatus === 503 ? 'Service Unavailable' : 'OK',
        headers: { 'content-type': 'application/json' },
      });
    }
    if (url.includes('/costs/per-trade')) {
      return new Response(JSON.stringify(opts.perTradeBody ?? SAMPLE_PER_TRADE), {
        status: opts.perTradeStatus ?? 200,
        statusText: opts.perTradeStatus === 503 ? 'Service Unavailable' : 'OK',
        headers: { 'content-type': 'application/json' },
      });
    }
    return new Response(JSON.stringify(opts.summaryBody ?? SAMPLE_SUMMARY), {
      status: opts.summaryStatus ?? 200,
      statusText: opts.summaryStatus === 503 ? 'Service Unavailable' : 'OK',
      headers: { 'content-type': 'application/json' },
    });
  });
}

describe('costs page load()', () => {
  it('happy path propagates summary + by-provider + per-trade', async () => {
    const load = await importLoad();
    const fetchSpy = mockTriple({});

    const event = buildEvent({ cookieValue: 'jwt-blob' });
    const result = (await load(event as never)) as LoadResult;

    expect(fetchSpy).toHaveBeenCalledTimes(3);
    const urls = fetchSpy.mock.calls.map((c) => c[0] as string);
    expect(urls.some((u) => u.endsWith('/api/v1/costs/summary'))).toBe(true);
    expect(urls.some((u) => u.endsWith('/api/v1/costs/by-provider'))).toBe(true);
    expect(urls.some((u) => u.endsWith('/api/v1/costs/per-trade'))).toBe(true);
    expect(result.loadError).toBeNull();
    expect(result.summary?.total_cost_usd).toBe('12.45');
    expect(result.byProvider?.breakdown).toHaveLength(2);
    expect(result.perTrade?.cost_per_trade_usd).toBe('2.49');

    fetchSpy.mockRestore();
  });

  it('empty (total_calls === 0) propagates as zero summary', async () => {
    const load = await importLoad();
    const emptySummary: CostSummaryDTO = {
      ...SAMPLE_SUMMARY,
      total_cost_usd: '0.00',
      total_calls: 0,
      cached_calls: 0,
    };
    const emptyByProvider: CostByProviderDTO = { ...SAMPLE_BY_PROVIDER, breakdown: [] };
    const emptyPerTrade: CostPerTradeDTO = {
      ...SAMPLE_PER_TRADE,
      total_llm_cost_usd: '0.00',
      closed_trades_count: 0,
      cost_per_trade_usd: null,
    };
    const fetchSpy = mockTriple({
      summaryBody: emptySummary,
      byProviderBody: emptyByProvider,
      perTradeBody: emptyPerTrade,
    });

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.loadError).toBeNull();
    expect(result.summary?.total_calls).toBe(0);
    expect(result.byProvider?.breakdown).toEqual([]);
    expect(result.perTrade?.cost_per_trade_usd).toBeNull();

    fetchSpy.mockRestore();
  });

  it.each([
    ['summary', { summaryStatus: 503 }],
    ['by-provider', { byProviderStatus: 503 }],
    ['per-trade', { perTradeStatus: 503 }],
  ] as const)('populates loadError when %s returns 503', async (_label, opts) => {
    const load = await importLoad();
    const fetchSpy = mockTriple(opts);

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.loadError).toContain('503');
    expect(result.summary).toBeNull();
    expect(result.byProvider).toBeNull();
    expect(result.perTrade).toBeNull();

    fetchSpy.mockRestore();
  });

  it('cost_per_trade_usd === null propagates verbatim and maps to "destructive"', async () => {
    const load = await importLoad();
    const fetchSpy = mockTriple({
      perTradeBody: {
        ...SAMPLE_PER_TRADE,
        closed_trades_count: 0,
        cost_per_trade_usd: null,
      },
    });

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.perTrade?.cost_per_trade_usd).toBeNull();
    expect(
      costPerTradeColour(
        result.perTrade?.cost_per_trade_usd === null
          ? null
          : Number(result.perTrade?.cost_per_trade_usd),
      ),
    ).toBe('destructive');

    fetchSpy.mockRestore();
  });

  it('high cost-per-trade (>5 USD) propagates and maps to "destructive"', async () => {
    const load = await importLoad();
    const fetchSpy = mockTriple({
      perTradeBody: {
        ...SAMPLE_PER_TRADE,
        total_llm_cost_usd: '128.90',
        closed_trades_count: 18,
        cost_per_trade_usd: '7.16',
      },
    });

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.perTrade?.cost_per_trade_usd).toBe('7.16');
    expect(costPerTradeColour(Number(result.perTrade?.cost_per_trade_usd))).toBe('destructive');

    fetchSpy.mockRestore();
  });
});
