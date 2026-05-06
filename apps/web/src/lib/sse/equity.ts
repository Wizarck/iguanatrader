/**
 * Equity SSE consumer — slice W1.
 *
 * Thin wrapper over `useSSE('equity', opts)`. Backend owner: T4
 * (`trading-routes-and-daemon`) ships `apps/api/src/iguanatrader/api/sse/equity.py`.
 *
 * Until the backend route lands, the consumer connects, receives a 404
 * from the dynamic-discovery loop (slice 5 contract), and cycles
 * `'reconnecting'` → `'closed'` after the canonical
 * `[3, 6, 12, 24, 48]`-second backoff exhaustion. No exception escapes
 * to the calling page (per spec scenario "Backend SSE route absent —
 * consumer gracefully closes").
 */

import { useSSE, type SSEHandle, type SSEOptions } from '$lib/composables/useSSE';

export function connectEquityStream(opts: SSEOptions = {}): SSEHandle {
  return useSSE('equity', opts);
}
