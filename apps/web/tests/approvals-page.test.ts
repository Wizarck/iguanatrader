/**
 * Approvals dashboard page tests (slice approvals-dashboard-ui).
 *
 * Covers the `+page.server.ts` load + actions end-to-end:
 *
 *   1. Happy path — pending list returns 2 approvals from API.
 *   2. Empty list — API returns [].
 *   3. API 503 → `loadError`.
 *   4. Approve action → POST + redirect(303, /approvals).
 *   5. Reject action with empty/null reason → POST { reason: null } + redirect.
 *   6. Reject action with reason → POST { reason } + redirect.
 *   7. Expired countdown — covered indirectly via the pure `formatCountdown`
 *      contract, asserted here on a real `ApprovalRequest` payload (delta
 *      negative → "Expired").
 */

import { describe, expect, it, vi } from 'vitest';

import { formatCountdown } from '../src/lib/approvals/countdown';
import type { ApprovalRequest } from '../src/lib/approvals/types';

async function importModule() {
  return await import('../src/routes/(app)/approvals/+page.server');
}

function buildLoadEvent(cookieValue: string | null = 'jwt-blob') {
  const cookies = new Map<string, string>();
  if (cookieValue !== null) cookies.set('iguana_session', cookieValue);
  return {
    fetch: (...args: Parameters<typeof fetch>) => globalThis.fetch(...args),
    cookies: { get: (name: string) => cookies.get(name) ?? null },
  };
}

function buildActionEvent(formData: Record<string, string>) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(formData)) {
    fd.append(k, v);
  }
  const cookies = new Map<string, string>();
  cookies.set('iguana_session', 'jwt-blob');
  return {
    request: { formData: async () => fd },
    fetch: (...args: Parameters<typeof fetch>) => globalThis.fetch(...args),
    cookies: { get: (name: string) => cookies.get(name) ?? null },
  };
}

const SAMPLE_APPROVALS: ApprovalRequest[] = [
  {
    id: '11111111-1111-1111-1111-111111111111',
    tenant_id: '00000000-0000-0000-0000-0000000000aa',
    proposal_id: '22222222-2222-2222-2222-222222222222',
    delivered_to_channels: ['telegram', 'whatsapp'],
    timeout_seconds: 300,
    expires_at: '2026-05-14T12:05:00Z',
    created_at: '2026-05-14T12:00:00Z',
    delivery_failures: null,
  },
  {
    id: '33333333-3333-3333-3333-333333333333',
    tenant_id: '00000000-0000-0000-0000-0000000000aa',
    proposal_id: '44444444-4444-4444-4444-444444444444',
    delivered_to_channels: ['dashboard'],
    timeout_seconds: 120,
    expires_at: '2026-05-14T12:02:00Z',
    created_at: '2026-05-14T12:00:00Z',
    delivery_failures: [{ channel: 'telegram', error: 'timeout' }],
  },
];

const VALID_REQ_ID = '11111111-1111-1111-1111-111111111111';

describe('approvals load()', () => {
  it('happy path returns pending approvals from API', async () => {
    const { load } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_APPROVALS), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const event = buildLoadEvent();
    const result = (await load(event as never)) as {
      approvals: ApprovalRequest[];
      loadError: string | null;
    };

    expect(fetchSpy).toHaveBeenCalledOnce();
    const url = fetchSpy.mock.calls[0][0] as string;
    expect(url).toContain('/api/v1/approvals');
    expect(result.approvals).toHaveLength(2);
    expect(result.approvals[0].id).toBe(VALID_REQ_ID);
    expect(result.loadError).toBeNull();

    fetchSpy.mockRestore();
  });

  it('returns empty list when API returns []', async () => {
    const { load } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('[]', {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const event = buildLoadEvent();
    const result = (await load(event as never)) as {
      approvals: ApprovalRequest[];
      loadError: string | null;
    };

    expect(result.approvals).toEqual([]);
    expect(result.loadError).toBeNull();

    fetchSpy.mockRestore();
  });

  it('surfaces loadError on 503', async () => {
    const { load } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('', { status: 503, statusText: 'Service Unavailable' }),
    );

    const event = buildLoadEvent();
    const result = (await load(event as never)) as {
      approvals: ApprovalRequest[];
      loadError: string | null;
    };

    expect(result.approvals).toEqual([]);
    expect(result.loadError).toContain('503');

    fetchSpy.mockRestore();
  });
});

describe('approvals approve action', () => {
  it('throws redirect(303, /approvals) on successful POST', async () => {
    const { actions } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok', message: 'approved', extra: null }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const event = buildActionEvent({ request_id: VALID_REQ_ID });

    let thrown: unknown;
    try {
      await actions!.approve!(event as never);
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeDefined();
    expect((thrown as { status: number }).status).toBe(303);
    expect((thrown as { location: string }).location).toBe('/approvals');

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [calledUrl, init] = fetchSpy.mock.calls[0];
    expect(calledUrl).toContain(`/api/v1/approvals/${VALID_REQ_ID}/approve`);
    expect((init as RequestInit).method).toBe('POST');

    fetchSpy.mockRestore();
  });

  it('fails 400 when request_id is missing', async () => {
    const { actions } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    const event = buildActionEvent({});
    const result = await actions!.approve!(event as never);

    expect((result as { status: number }).status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();

    fetchSpy.mockRestore();
  });
});

describe('approvals reject action', () => {
  it('throws redirect on POST with null reason when reason is empty', async () => {
    const { actions } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok', message: 'rejected', extra: null }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const event = buildActionEvent({ request_id: VALID_REQ_ID, reason: '' });

    let thrown: unknown;
    try {
      await actions!.reject!(event as never);
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeDefined();
    expect((thrown as { status: number }).status).toBe(303);

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [calledUrl, init] = fetchSpy.mock.calls[0];
    expect(calledUrl).toContain(`/api/v1/approvals/${VALID_REQ_ID}/reject`);
    expect((init as RequestInit).method).toBe('POST');
    const body = JSON.parse((init as RequestInit).body as string) as { reason: string | null };
    expect(body.reason).toBeNull();

    fetchSpy.mockRestore();
  });

  it('throws redirect on POST with reason when reason provided', async () => {
    const { actions } = await importModule();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok', message: 'rejected', extra: null }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const event = buildActionEvent({
      request_id: VALID_REQ_ID,
      reason: 'riesgo demasiado alto',
    });

    let thrown: unknown;
    try {
      await actions!.reject!(event as never);
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeDefined();
    expect((thrown as { status: number }).status).toBe(303);

    const [, init] = fetchSpy.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string) as { reason: string | null };
    expect(body.reason).toBe('riesgo demasiado alto');

    fetchSpy.mockRestore();
  });
});

describe('expired countdown contract (sanity)', () => {
  it('returns "Expired" when an approval row is past its expiry', () => {
    const approval = SAMPLE_APPROVALS[1];
    const now = new Date('2026-05-14T13:00:00Z');
    expect(formatCountdown(approval.expires_at, now)).toBe('Expired');
  });
});
