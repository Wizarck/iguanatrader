/**
 * Costs SSE consumer — slice W1.
 *
 * Thin wrapper over `useSSE('costs', opts)`. Backend owner: O1
 * (`observability-cost-meter`).
 */

import { useSSE, type SSEHandle, type SSEOptions } from '$lib/composables/useSSE';

export function connectCostsStream(opts: SSEOptions = {}): SSEHandle {
  return useSSE('costs', opts);
}
