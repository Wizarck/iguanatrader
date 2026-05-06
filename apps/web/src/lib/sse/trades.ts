/**
 * Trades SSE consumer — slice W1.
 *
 * Thin wrapper over `useSSE('trades', opts)`. Backend owner: T4
 * (`trading-routes-and-daemon`).
 */

import { useSSE, type SSEHandle, type SSEOptions } from '$lib/composables/useSSE';

export function connectTradesStream(opts: SSEOptions = {}): SSEHandle {
  return useSSE('trades', opts);
}
