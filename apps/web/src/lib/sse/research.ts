/**
 * Research SSE consumer — slice W1.
 *
 * Thin wrapper over `useSSE('research', opts)`. Backend owner: R5
 * (`research-brief-synthesis`).
 */

import { useSSE, type SSEHandle, type SSEOptions } from '$lib/composables/useSSE';

export function connectResearchStream(opts: SSEOptions = {}): SSEHandle {
  return useSSE('research', opts);
}
