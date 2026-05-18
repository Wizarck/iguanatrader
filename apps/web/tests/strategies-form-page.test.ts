/**
 * Strategy edit/upsert form page tests (slice strategies-config-ui).
 *
 * Covers the `[symbol]/+page.server.ts` load + actions end-to-end:
 *
 *   1. New mode load — `mode === 'new'`, strategy null, no fetch fired.
 *   2. Edit mode load — `mode === 'edit'`, strategy pre-filled from API.
 *   3. Edit mode load 404 — `loadError` populated.
 *   4. Upsert with invalid JSON params → fail(400) with fieldErrors.params.
 *   5. Upsert with invalid symbol pattern → fail(400) with fieldErrors.symbol.
 *   6. Upsert with invalid strategy_kind → fail(400) with fieldErrors.strategy_kind.
 *   7. Upsert happy path → throws redirect(303, '/strategies').
 *   8. Disable action happy path → throws redirect(303, '/strategies').
 */

import { describe, expect, it, vi } from 'vitest';

import type { StrategyConfigOut } from '../src/lib/strategies/types';

async function importModule() {
  return await import('../src/routes/(app)/strategies/[symbol]/+page.server');
}

function buildLoadEvent(
  params: { symbol: string },
  cookieValue = 'jwt-blob',
  url: URL = new URL('https://test.local/strategies/new'),
) {
  const cookies = new Map<string, string>();
  cookies.set('iguana_session', cookieValue);
  return {
    fetch: (...args: Parameters<typeof fetch>) => globalThis.fetch(...args),
    cookies: { get: (name: string) => cookies.get(name) ?? null },
    params,
    url,
  };
}

function buildActionEvent(opts: {
  symbol: string;
  formData: Record<string, string>;
}) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(opts.formData)) {
    fd.append(k, v);
  }
  const cookies = new Map<string, string>();
  cookies.set('iguana_session', 'jwt-blob');
  return {
    request: { formData: async () => fd },
    fetch: (...args: Parameters<typeof fetch>) => globalThis.fetch(...args),
    cookies: { get: (name: string) => cookies.get(name) ?? null },
    params: { symbol: opts.symbol },
  };
}

const SAMPLE_STRATEGY: StrategyConfigOut = {
  id: '00000000-0000-0000-0000-000000000001',
  tenant_id: '00000000-0000-0000-0000-0000000000aa',
  strategy_kind: 'donchian_atr',
  symbol: 'SPY',
  params: { lookback: 20, atr_mult: 2.0 },
  enabled: true,
  version: 2,
  created_at: '2026-05-01T10:00:00Z',
  updated_at: '2026-05-13T09:00:00Z',
};

describe('strategy form load()', () => {
  it('new mode returns empty form without firing fetch', async () => {
    const { load } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    const event = buildLoadEvent({ symbol: 'new' });
    const result = (await load(event as never)) as {
      mode: string;
      strategy: StrategyConfigOut | null;
      loadError: string | null;
      symbolPrefill: string;
    };

    expect(result.mode).toBe('new');
    expect(result.strategy).toBeNull();
    expect(result.loadError).toBeNull();
    expect(result.symbolPrefill).toBe('');
    expect(fetchSpy).not.toHaveBeenCalled();

    fetchSpy.mockRestore();
  });

  it('new mode prefills symbol from ?symbol= query param', async () => {
    const { load } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    const url = new URL('https://test.local/strategies/new?symbol=AMD');
    const event = buildLoadEvent({ symbol: 'new' }, 'jwt-blob', url);
    const result = (await load(event as never)) as {
      mode: string;
      strategy: StrategyConfigOut | null;
      loadError: string | null;
      symbolPrefill: string;
    };

    expect(result.mode).toBe('new');
    expect(result.symbolPrefill).toBe('AMD');
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it('new mode rejects an invalid ?symbol= query value', async () => {
    const { load } = await importModule();
    const url = new URL('https://test.local/strategies/new?symbol=amd%20lower!');
    const event = buildLoadEvent({ symbol: 'new' }, 'jwt-blob', url);
    const result = (await load(event as never)) as { symbolPrefill: string };
    expect(result.symbolPrefill).toBe('');
  });

  it('edit mode pre-fills strategy from API', async () => {
    const { load } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_STRATEGY), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const event = buildLoadEvent({ symbol: 'SPY' });
    const result = (await load(event as never)) as {
      mode: string;
      strategy: StrategyConfigOut | null;
      loadError: string | null;
    };

    expect(fetchSpy).toHaveBeenCalledOnce();
    const url = fetchSpy.mock.calls[0][0] as string;
    expect(url).toContain('/api/v1/strategies/SPY');
    expect(result.mode).toBe('edit');
    expect(result.strategy?.symbol).toBe('SPY');
    expect(result.strategy?.strategy_kind).toBe('donchian_atr');
    expect(result.loadError).toBeNull();

    fetchSpy.mockRestore();
  });

  it('edit mode 404 surfaces loadError instead of throwing', async () => {
    const { load } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('', { status: 404, statusText: 'Not Found' }),
    );

    const event = buildLoadEvent({ symbol: 'GME' });
    const result = (await load(event as never)) as {
      mode: string;
      strategy: StrategyConfigOut | null;
      loadError: string | null;
    };

    expect(result.mode).toBe('edit');
    expect(result.strategy).toBeNull();
    expect(result.loadError).toContain('GME');

    fetchSpy.mockRestore();
  });
});

describe('strategy form upsert action', () => {
  it('fails 400 with fieldErrors.params on invalid JSON', async () => {
    const { actions } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    const event = buildActionEvent({
      symbol: 'SPY',
      formData: {
        mode: 'edit',
        symbol: 'SPY',
        strategy_kind: 'donchian_atr',
        params: '{not-json',
        enabled: 'on',
      },
    });
    const result = await actions!.upsert!(event as never);

    expect((result as { status: number }).status).toBe(400);
    const data = (result as { data: { fieldErrors: Record<string, string> } }).data;
    expect(data.fieldErrors.params).toContain('Invalid JSON');
    expect(fetchSpy).not.toHaveBeenCalled();

    fetchSpy.mockRestore();
  });

  it('fails 400 with fieldErrors.symbol on invalid symbol pattern', async () => {
    const { actions } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    const event = buildActionEvent({
      symbol: 'new',
      formData: {
        mode: 'new',
        symbol: 'spy lower!',
        strategy_kind: 'donchian_atr',
        params: '{"lookback": 20, "atr_mult": 2.0}',
        enabled: 'on',
      },
    });
    const result = await actions!.upsert!(event as never);

    expect((result as { status: number }).status).toBe(400);
    const data = (result as { data: { fieldErrors: Record<string, string> } }).data;
    expect(data.fieldErrors.symbol).toContain('Invalid symbol');
    expect(fetchSpy).not.toHaveBeenCalled();

    fetchSpy.mockRestore();
  });

  it('fails 400 with fieldErrors.strategy_kind on unknown kind', async () => {
    const { actions } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    const event = buildActionEvent({
      symbol: 'SPY',
      formData: {
        mode: 'edit',
        symbol: 'SPY',
        strategy_kind: 'mean_reversion_v9',
        params: '{"x": 1}',
        enabled: 'on',
      },
    });
    const result = await actions!.upsert!(event as never);

    expect((result as { status: number }).status).toBe(400);
    const data = (result as { data: { fieldErrors: Record<string, string> } }).data;
    expect(data.fieldErrors.strategy_kind).toContain('Invalid strategy kind');
    expect(fetchSpy).not.toHaveBeenCalled();

    fetchSpy.mockRestore();
  });

  it('throws redirect(303) on successful PUT', async () => {
    const { actions } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_STRATEGY), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const event = buildActionEvent({
      symbol: 'SPY',
      formData: {
        mode: 'edit',
        symbol: 'SPY',
        strategy_kind: 'donchian_atr',
        params: '{"lookback": 20, "atr_mult": 2.0}',
        enabled: 'on',
      },
    });

    let thrown: unknown;
    try {
      await actions!.upsert!(event as never);
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeDefined();
    expect((thrown as { status: number }).status).toBe(303);
    expect((thrown as { location: string }).location).toBe('/strategies');

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [calledUrl, init] = fetchSpy.mock.calls[0];
    expect(calledUrl).toContain('/api/v1/strategies/SPY');
    expect((init as RequestInit).method).toBe('PUT');
    const body = JSON.parse((init as RequestInit).body as string) as {
      strategy_kind: string;
      params: Record<string, number>;
      enabled: boolean;
    };
    expect(body.strategy_kind).toBe('donchian_atr');
    expect(body.params.lookback).toBe(20);
    expect(body.enabled).toBe(true);

    fetchSpy.mockRestore();
  });
});

describe('strategy form disable action', () => {
  it('throws redirect(303, /strategies) on successful DELETE', async () => {
    const { actions } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'disabled', symbol: 'SPY' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const event = buildActionEvent({
      symbol: 'SPY',
      formData: {},
    });

    let thrown: unknown;
    try {
      await actions!.disable!(event as never);
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeDefined();
    expect((thrown as { status: number }).status).toBe(303);
    expect((thrown as { location: string }).location).toBe('/strategies');

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [calledUrl, init] = fetchSpy.mock.calls[0];
    expect(calledUrl).toContain('/api/v1/strategies/SPY');
    expect((init as RequestInit).method).toBe('DELETE');

    fetchSpy.mockRestore();
  });

  it('returns fail(400) when symbol is "new"', async () => {
    const { actions } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    const event = buildActionEvent({ symbol: 'new', formData: {} });
    const result = await actions!.disable!(event as never);

    expect((result as { status: number }).status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();

    fetchSpy.mockRestore();
  });
});
