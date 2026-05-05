/**
 * Alerts SSE consumer — slice W1.
 *
 * Thin wrapper over `useSSE('alerts', opts)`. Backend owner: O2
 * (`orchestration-scheduler-routines`).
 */

import { useSSE, type SSEHandle, type SSEOptions } from '$lib/composables/useSSE';

export function connectAlertsStream(opts: SSEOptions = {}): SSEHandle {
  return useSSE('alerts', opts);
}
