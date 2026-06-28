/**
 * Portfolio dashboard page tests (slice portfolio-dashboard-mvp).
 *
 * Covers the `+page.server.ts` load fn end-to-end with mocked fetch
 * over the 3 upstream endpoints:
 *
 *   1. Happy path — all 3 endpoints 200; summary + positions + series propagate.
 *   2. All-empty — `snapshot_kind="empty"` + zero positions + zero series.
 *   3. API 503 on any of the 3 → `loadError` set + page does not crash.
 *   4. Negative day P&L → `day_pnl_abs` < 0 carried through verbatim.
 *   5. Null day P&L → `day_pnl_abs: null` carried through verbatim.
 *   6. Positions with null `last_price` propagate as null (formatted to "—" by UI).
 */

import { describe, expect, it, vi } from 'vitest';

import type {
  EquitySnapshotListOut,
  EquitySnapshotOut,
  PortfolioSummaryOut,
  PositionListOut,
  PositionOut,
} from '../src/lib/portfolio/types';

async function importLoad() {
  const mod = await import('../src/routes/(app)/portfolio/+page.server');
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

const SAMPLE_EQUITY: EquitySnapshotOut = {
  id: '00000000-0000-0000-0000-0000000000e1',
  tenant_id: TENANT_ID,
  mode: 'paper',
  account_equity: '100237.45',
  cash_balance: '50000.00',
  realized_pnl_today: '250.75',
  unrealized_pnl: '125.50',
  currency: 'USD',
  snapshot_kind: 'event',
  created_at: '2026-05-13T09:00:00Z',
};

const SAMPLE_SUMMARY: PortfolioSummaryOut = {
  equity: SAMPLE_EQUITY,
  open_trades: [],
  open_orders: [],
  day_pnl_abs: '237.45',
  day_pnl_pct: '0.00237',
};

const SAMPLE_POSITION: PositionOut = {
  trade_id: '00000000-0000-0000-0000-000000000001',
  symbol: 'AAPL',
  side: 'buy',
  quantity: '10',
  avg_entry_price: '180.50',
  last_price: null,
  unrealized_pnl: null,
  marks_updated_at: null,
  opened_at: '2026-05-01T10:00:00Z',
  strategy_kind: 'donchian_atr',
  entry_price_indicative: '179.90',
  stop_price: '172.00',
  target_price: '198.00',
  // Position recommendation scorecard fields (often null in practice).
  confidence_score: '0.62',
  reasoning: { trigger: 'donchian_breakout', atr: '3.21' },
  horizon_days: 20,
  horizon_label: 'short',
  held_market_days: 8,
  r_multiple: '0.41',
  rail_progress: '0.33',
  reward_risk: '2.1',
  verdict: 'too_early',
  verdict_reason: 'Too few sessions held to judge the thesis yet.',
};

const SAMPLE_POSITIONS: PositionListOut = {
  items: [SAMPLE_POSITION],
  total: 1,
};

const SAMPLE_SERIES: EquitySnapshotListOut = {
  items: [
    { ...SAMPLE_EQUITY, account_equity: '100000.00' },
    { ...SAMPLE_EQUITY, account_equity: '100100.00' },
    { ...SAMPLE_EQUITY, account_equity: '100237.45' },
  ],
  next_cursor: null,
  total: 3,
};

type LoadResult = {
  summary: PortfolioSummaryOut | null;
  positions: PositionOut[];
  equity_series: EquitySnapshotOut[];
  loadError: string | null;
};

function mockTriple(opts: {
  summaryStatus?: number;
  positionsStatus?: number;
  seriesStatus?: number;
  summaryBody?: unknown;
  positionsBody?: unknown;
  seriesBody?: unknown;
}) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: string | URL | Request) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.includes('/equity/series')) {
      return new Response(JSON.stringify(opts.seriesBody ?? SAMPLE_SERIES), {
        status: opts.seriesStatus ?? 200,
        statusText: opts.seriesStatus === 503 ? 'Service Unavailable' : 'OK',
        headers: { 'content-type': 'application/json' },
      });
    }
    if (url.includes('/positions')) {
      return new Response(JSON.stringify(opts.positionsBody ?? SAMPLE_POSITIONS), {
        status: opts.positionsStatus ?? 200,
        statusText: opts.positionsStatus === 503 ? 'Service Unavailable' : 'OK',
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

describe('portfolio page load()', () => {
  it('happy path propagates summary + positions + series', async () => {
    const load = await importLoad();
    const fetchSpy = mockTriple({});

    const event = buildEvent({ cookieValue: 'jwt-blob' });
    const result = (await load(event as never)) as LoadResult;

    expect(fetchSpy).toHaveBeenCalledTimes(3);
    const urls = fetchSpy.mock.calls.map((c) => c[0] as string);
    expect(urls.some((u) => u.endsWith('/api/v1/portfolio'))).toBe(true);
    expect(urls.some((u) => u.includes('/portfolio/positions'))).toBe(true);
    expect(urls.some((u) => u.includes('/portfolio/equity/series?days=30'))).toBe(true);
    expect(result.loadError).toBeNull();
    expect(result.summary?.equity.account_equity).toBe('100237.45');
    expect(result.positions).toHaveLength(1);
    expect(result.equity_series).toHaveLength(3);

    fetchSpy.mockRestore();
  });

  it('all-empty propagates snapshot_kind="empty" + zero positions + zero series', async () => {
    const load = await importLoad();
    const emptySummary: PortfolioSummaryOut = {
      ...SAMPLE_SUMMARY,
      equity: { ...SAMPLE_EQUITY, snapshot_kind: 'empty' },
      day_pnl_abs: null,
      day_pnl_pct: null,
    };
    const fetchSpy = mockTriple({
      summaryBody: emptySummary,
      positionsBody: { items: [], total: 0 },
      seriesBody: { items: [], next_cursor: null, total: 0 },
    });

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.loadError).toBeNull();
    expect(result.summary?.equity.snapshot_kind).toBe('empty');
    expect(result.positions).toEqual([]);
    expect(result.equity_series).toEqual([]);

    fetchSpy.mockRestore();
  });

  it.each([
    ['summary', { summaryStatus: 503 }],
    ['positions', { positionsStatus: 503 }],
    ['series', { seriesStatus: 503 }],
  ] as const)('populates loadError when %s returns 503', async (_label, opts) => {
    const load = await importLoad();
    const fetchSpy = mockTriple(opts);

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.loadError).toContain('503');
    expect(result.summary).toBeNull();
    expect(result.positions).toEqual([]);
    expect(result.equity_series).toEqual([]);

    fetchSpy.mockRestore();
  });

  it('negative day P&L is carried through verbatim', async () => {
    const load = await importLoad();
    const fetchSpy = mockTriple({
      summaryBody: {
        ...SAMPLE_SUMMARY,
        day_pnl_abs: '-150.25',
        day_pnl_pct: '-0.00150',
      },
    });

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.summary?.day_pnl_abs).toBe('-150.25');
    expect(result.summary?.day_pnl_pct).toBe('-0.00150');

    fetchSpy.mockRestore();
  });

  it('null day P&L is carried through verbatim (no fake-zero)', async () => {
    const load = await importLoad();
    const fetchSpy = mockTriple({
      summaryBody: {
        ...SAMPLE_SUMMARY,
        day_pnl_abs: null,
        day_pnl_pct: null,
      },
    });

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.summary?.day_pnl_abs).toBeNull();
    expect(result.summary?.day_pnl_pct).toBeNull();

    fetchSpy.mockRestore();
  });

  it('positions with null last_price / unrealized_pnl propagate as null', async () => {
    const load = await importLoad();
    const fetchSpy = mockTriple({});

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.positions[0].last_price).toBeNull();
    expect(result.positions[0].unrealized_pnl).toBeNull();

    fetchSpy.mockRestore();
  });

  it('populates loadError on network throw', async () => {
    const load = await importLoad();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('ECONNREFUSED'));

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.loadError).toContain('ECONNREFUSED');
    expect(result.summary).toBeNull();

    fetchSpy.mockRestore();
  });
});
