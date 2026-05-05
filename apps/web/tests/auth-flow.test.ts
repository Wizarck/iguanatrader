/**
 * Slice 4 frontend e2e — vitest covers what would otherwise be a
 * Playwright suite, focused on the boundary cases that matter:
 *
 * 1. `safeRedirectTo` allow-list (D9).
 * 2. Cookie hook redirects unauthenticated `(app)` requests to
 *    `/login?redirect_to=<encoded>` and stashes the user on
 *    `event.locals.user` when the FastAPI `/me` returns 200.
 * 3. Login form action proxies to FastAPI, propagates the cookie on
 *    200, and returns the right `fail` shape on 401 / 429 / 503.
 *
 * A real browser walk (cold visit → 302 → submit → land) needs
 * Playwright spinning up vite-dev + FastAPI; that's documented as a
 * follow-up gotcha for slice W1 e2e harness.
 */

import { describe, expect, it, vi } from 'vitest';

import { safeRedirectTo } from '../src/lib/redirect';

// --------------------------------------------------------------------- //
// 1. safeRedirectTo
// --------------------------------------------------------------------- //

describe('safeRedirectTo', () => {
  it('returns / for null/undefined/empty', () => {
    expect(safeRedirectTo(null)).toBe('/');
    expect(safeRedirectTo(undefined)).toBe('/');
    expect(safeRedirectTo('')).toBe('/');
  });

  it('accepts a single-leading-slash path', () => {
    expect(safeRedirectTo('/portfolio')).toBe('/portfolio');
    expect(safeRedirectTo('/portfolio?range=last-7d')).toBe(
      '/portfolio?range=last-7d'
    );
    expect(safeRedirectTo('/a/b/c')).toBe('/a/b/c');
  });

  it('falls back to / on protocol-relative URLs', () => {
    expect(safeRedirectTo('//evil.com')).toBe('/');
  });

  it('falls back to / on absolute URLs', () => {
    expect(safeRedirectTo('https://evil.com/phish')).toBe('/');
    expect(safeRedirectTo('http://evil.com')).toBe('/');
  });

  it('falls back to / on backslash-bearing values', () => {
    expect(safeRedirectTo('/\\evil.com')).toBe('/');
    expect(safeRedirectTo('\\evil.com')).toBe('/');
  });

  it('falls back to / when not starting with /', () => {
    expect(safeRedirectTo('portfolio')).toBe('/');
    expect(safeRedirectTo('javascript:alert(1)')).toBe('/');
  });
});

// --------------------------------------------------------------------- //
// 2. Cookie hook
// --------------------------------------------------------------------- //

describe('hooks.server.ts handle()', () => {
  async function importHandle() {
    const mod = await import('../src/hooks.server');
    return mod.handle;
  }

  function buildEvent(opts: {
    routeId: string | null;
    pathname: string;
    search?: string;
    cookieValue?: string;
  }) {
    const cookieMap = new Map<string, string>();
    if (opts.cookieValue) cookieMap.set('iguana_session', opts.cookieValue);

    return {
      route: { id: opts.routeId },
      url: new URL(`https://test${opts.pathname}${opts.search ?? ''}`),
      cookies: {
        get: (name: string) => cookieMap.get(name) ?? null
      },
      locals: {} as App.Locals
    };
  }

  it('passes through ungated routes without checking the cookie', async () => {
    const handle = await importHandle();
    const event = buildEvent({ routeId: '/(auth)/login', pathname: '/login' });
    const resolve = vi.fn().mockResolvedValue(new Response('ok'));

    await handle({ event: event as never, resolve });

    expect(resolve).toHaveBeenCalledOnce();
    expect(event.locals.user).toBeNull();
  });

  it('redirects unauthenticated (app) requests with encoded redirect_to', async () => {
    const handle = await importHandle();
    const event = buildEvent({
      routeId: '/(app)/portfolio',
      pathname: '/portfolio',
      search: '?range=last-7d'
    });
    const resolve = vi.fn();

    let thrown: unknown;
    try {
      await handle({ event: event as never, resolve });
    } catch (err) {
      thrown = err;
    }

    // SvelteKit's `redirect()` throws an object with status + location.
    expect(thrown).toBeDefined();
    expect((thrown as { status: number }).status).toBe(302);
    const location = (thrown as { location: string }).location;
    expect(location).toBe(
      `/login?redirect_to=${encodeURIComponent('/portfolio?range=last-7d')}`
    );
    expect(resolve).not.toHaveBeenCalled();
  });

  it('stashes user on locals when /me returns 200', async () => {
    const handle = await importHandle();
    const event = buildEvent({
      routeId: '/(app)/portfolio',
      pathname: '/portfolio',
      cookieValue: 'fake-jwt'
    });
    const resolve = vi.fn().mockResolvedValue(new Response('ok'));

    const userPayload = {
      user_id: '00000000-0000-0000-0000-000000000001',
      tenant_id: '00000000-0000-0000-0000-000000000002',
      email: 'alice@example.com',
      role: 'tenant_user' as const,
      created_at: '2026-01-01T00:00:00Z'
    };
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(userPayload), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      })
    );

    await handle({ event: event as never, resolve });

    expect(fetchSpy).toHaveBeenCalledOnce();
    const calledUrl = fetchSpy.mock.calls[0][0] as string;
    expect(calledUrl).toContain('/api/v1/auth/me');
    expect(event.locals.user).toEqual(userPayload);
    expect(resolve).toHaveBeenCalledOnce();

    fetchSpy.mockRestore();
  });
});

// --------------------------------------------------------------------- //
// 3. Login form action
// --------------------------------------------------------------------- //

describe('login form action', () => {
  async function importAction() {
    const mod = await import('../src/routes/(auth)/login/+page.server');
    return mod.actions.default;
  }

  function buildEvent(opts: {
    formData: Record<string, string>;
    redirectTo?: string | null;
  }) {
    const fd = new FormData();
    for (const [k, v] of Object.entries(opts.formData)) {
      fd.append(k, v);
    }
    const cookiesSet: Array<{ name: string; value: string; opts: unknown }> = [];

    return {
      event: {
        request: {
          formData: async () => fd
        },
        // Lazy fetch reference so vi.spyOn(globalThis, 'fetch') installed
        // AFTER buildEvent() is honoured at call time.
        fetch: (...args: Parameters<typeof fetch>) => globalThis.fetch(...args),
        cookies: {
          set: (name: string, value: string, opts: unknown) =>
            cookiesSet.push({ name, value, opts })
        },
        url: new URL(
          `https://test/login${
            opts.redirectTo ? `?redirect_to=${encodeURIComponent(opts.redirectTo)}` : ''
          }`
        )
      },
      cookiesSet
    };
  }

  it('returns 401 fail on FastAPI 401', async () => {
    const action = await importAction();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{}', {
        status: 401,
        headers: { 'content-type': 'application/problem+json' }
      })
    );

    const { event } = buildEvent({
      formData: { email: 'x@y.z', password: 'wrong' }
    });
    const result = await action(event as never);

    expect((result as { status: number }).status).toBe(401);
    const data = (result as { data: { alert_variant: string; message: string } })
      .data;
    expect(data.alert_variant).toBe('destructive');
    expect(data.message).toContain('Invalid');

    fetchSpy.mockRestore();
  });

  it('returns 429 fail with retry_after on FastAPI 429', async () => {
    const action = await importAction();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{}', {
        status: 429,
        headers: {
          'content-type': 'application/problem+json',
          'retry-after': '47'
        }
      })
    );

    const { event } = buildEvent({
      formData: { email: 'x@y.z', password: 'x' }
    });
    const result = await action(event as never);

    expect((result as { status: number }).status).toBe(429);
    const data = (result as { data: { retry_after: number } }).data;
    expect(data.retry_after).toBe(47);

    fetchSpy.mockRestore();
  });

  it('returns 503 fail with detail on FastAPI 503', async () => {
    const action = await importAction();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ detail: 'Run iguanatrader admin bootstrap-tenant' }),
        {
          status: 503,
          headers: { 'content-type': 'application/problem+json' }
        }
      )
    );

    const { event } = buildEvent({
      formData: { email: 'x@y.z', password: 'x' }
    });
    const result = await action(event as never);

    expect((result as { status: number }).status).toBe(503);
    const data = (result as { data: { detail: string; alert_variant: string } })
      .data;
    expect(data.alert_variant).toBe('warn');
    expect(data.detail).toContain('bootstrap-tenant');

    fetchSpy.mockRestore();
  });

  it('throws redirect(302, redirect_to) and propagates Set-Cookie on 200', async () => {
    const action = await importAction();
    const setCookieValue =
      'iguana_session=jwt-blob; HttpOnly; Secure; SameSite=Strict; Max-Age=604800; Path=/';
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"redirect_to":"/portfolio"}', {
        status: 200,
        headers: {
          'content-type': 'application/json',
          'set-cookie': setCookieValue
        }
      })
    );

    const { event, cookiesSet } = buildEvent({
      formData: { email: 'alice@example.com', password: 'pw' },
      redirectTo: '/portfolio'
    });

    let thrown: unknown;
    try {
      await action(event as never);
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeDefined();
    expect((thrown as { status: number }).status).toBe(302);
    expect((thrown as { location: string }).location).toBe('/portfolio');

    expect(cookiesSet).toHaveLength(1);
    expect(cookiesSet[0].name).toBe('iguana_session');
    expect(cookiesSet[0].value).toBe('jwt-blob');
    const opts = cookiesSet[0].opts as Record<string, unknown>;
    expect(opts.httpOnly).toBe(true);
    expect(opts.secure).toBe(true);
    expect(opts.sameSite).toBe('strict');
    expect(opts.maxAge).toBe(604800);

    fetchSpy.mockRestore();
  });

  it('falls back to / when redirect_to is malicious', async () => {
    const action = await importAction();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"redirect_to":"/"}', {
        status: 200,
        headers: {
          'content-type': 'application/json',
          'set-cookie': 'iguana_session=jwt; HttpOnly; Path=/'
        }
      })
    );

    const { event } = buildEvent({
      formData: { email: 'alice@example.com', password: 'pw' },
      redirectTo: 'https://evil.com/phish'
    });

    let thrown: unknown;
    try {
      await action(event as never);
    } catch (err) {
      thrown = err;
    }

    expect((thrown as { location: string }).location).toBe('/');

    fetchSpy.mockRestore();
  });
});
