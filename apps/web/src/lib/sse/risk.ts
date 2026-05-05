/**
 * Risk SSE consumer — slice W1.
 *
 * Thin wrapper over `useSSE('risk', opts)`. Backend owner: K1
 * (`risk-engine-protections`).
 */

import { useSSE, type SSEHandle, type SSEOptions } from '$lib/composables/useSSE';

export function connectRiskStream(opts: SSEOptions = {}): SSEHandle {
  return useSSE('risk', opts);
}
