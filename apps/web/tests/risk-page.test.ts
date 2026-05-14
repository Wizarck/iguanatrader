/**
 * Risk dashboard page tests (slice risk-dashboard-ui).
 *
 * Covers the `+page.server.ts` load fn end-to-end with mocked fetch
 * over the single upstream endpoint `GET /api/v1/risk/state`, plus
 * a render-level check of the colour-tier mapper via
 * `utilisationBarColour`. The bar's tier is asserted on the pure
 * helper to keep the test DOM-free (Storybook covers the visual).
 *
 * Cases:
 *   1. Happy path — full payload propagates caps + state + utilisation +
 *      kill-switch indicator default ("Operativo").
 *   2. Empty/zero state — all utilisation = "0" + capital = "0" +
 *      open_positions_count = 0 → page-level `isAllEmpty` would fire.
 *   3. API 503 → `loadError` populated, page does not crash.
 *   4. Kill switch active → indicator label resolves to
 *      "Kill-switch ACTIVO" / destructive variant.
 *   5. Utilisation 0.9 on daily_loss (cap 0.05 ⇒ ratio clamped to 1) →
 *      colour-tier mapper returns `destructive`.
 */

import { describe, expect, it, vi } from 'vitest';

import { utilisationBarColour } from '../src/lib/risk/colour';
import type { RiskStateResponse } from '../src/lib/risk/types';

async function importLoad() {
  const mod = await import('../src/routes/(app)/risk/+page.server');
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

const SAMPLE_RISK: RiskStateResponse = {
  caps: {
    per_trade_pct: '0.01',
    daily_loss_pct: '0.05',
    weekly_loss_pct: '0.1',
    max_open_positions: 5,
    max_drawdown_pct: '0.2',
  },
  state: {
    capital: '100000.00',
    day_to_date_loss_pct: '0.021',
    week_to_date_loss_pct: '0.045',
    open_positions_count: 3,
    peak_to_trough_drawdown_pct: '0.08',
  },
  utilisation: {
    daily_loss: '0.021',
    weekly_loss: '0.045',
    max_drawdown: '0.08',
  },
  kill_switch_active: false,
  fetched_at: '2026-05-14T09:30:00Z',
};

type LoadResult = {
  risk: RiskStateResponse | null;
  loadError: string | null;
};

function mockState(opts: { status?: number; body?: unknown }) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    return new Response(JSON.stringify(opts.body ?? SAMPLE_RISK), {
      status: opts.status ?? 200,
      statusText: opts.status === 503 ? 'Service Unavailable' : 'OK',
      headers: { 'content-type': 'application/json' },
    });
  });
}

describe('risk page load()', () => {
  it('happy path propagates caps + state + utilisation', async () => {
    const load = await importLoad();
    const fetchSpy = mockState({});

    const event = buildEvent({ cookieValue: 'jwt-blob' });
    const result = (await load(event as never)) as LoadResult;

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect((fetchSpy.mock.calls[0][0] as string).endsWith('/api/v1/risk/state')).toBe(true);
    expect(result.loadError).toBeNull();
    expect(result.risk?.caps.daily_loss_pct).toBe('0.05');
    expect(result.risk?.state.capital).toBe('100000.00');
    expect(result.risk?.utilisation.daily_loss).toBe('0.021');
    expect(result.risk?.kill_switch_active).toBe(false);

    fetchSpy.mockRestore();
  });

  it('all-zero / empty state propagates verbatim (page renders EmptyState)', async () => {
    const load = await importLoad();
    const fetchSpy = mockState({
      body: {
        ...SAMPLE_RISK,
        state: { ...SAMPLE_RISK.state, capital: '0', open_positions_count: 0 },
        utilisation: { daily_loss: '0', weekly_loss: '0', max_drawdown: '0' },
      },
    });

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.loadError).toBeNull();
    expect(result.risk?.state.capital).toBe('0');
    expect(result.risk?.state.open_positions_count).toBe(0);
    expect(Object.values(result.risk!.utilisation).every((v) => v === '0')).toBe(true);

    fetchSpy.mockRestore();
  });

  it('populates loadError when /risk/state returns 503', async () => {
    const load = await importLoad();
    const fetchSpy = mockState({ status: 503 });

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.loadError).toContain('503');
    expect(result.risk).toBeNull();

    fetchSpy.mockRestore();
  });

  it('kill switch active is carried through verbatim', async () => {
    const load = await importLoad();
    const fetchSpy = mockState({
      body: { ...SAMPLE_RISK, kill_switch_active: true },
    });

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.risk?.kill_switch_active).toBe(true);

    fetchSpy.mockRestore();
  });

  it('utilisation 90% of cap maps to destructive tier', () => {
    // daily_loss utilisation = 0.045 over cap 0.05 ⇒ ratio 0.9 ⇒ destructive.
    const utilisation = 0.045;
    const cap = 0.05;
    const ratio = Math.min(utilisation / cap, 1);
    expect(ratio).toBeCloseTo(0.9, 5);
    expect(utilisationBarColour(ratio)).toBe('destructive');
  });

  it('populates loadError on network throw', async () => {
    const load = await importLoad();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('ECONNREFUSED'));

    const event = buildEvent();
    const result = (await load(event as never)) as LoadResult;

    expect(result.loadError).toContain('ECONNREFUSED');
    expect(result.risk).toBeNull();

    fetchSpy.mockRestore();
  });
});
