/**
 * Approvals SSE consumer — slice W1.
 *
 * Thin wrapper over `useSSE('approvals', opts)`. Backend owner: P1
 * (`approval-channels-multichannel`).
 */

import { useSSE, type SSEHandle, type SSEOptions } from '$lib/composables/useSSE';

export function connectApprovalsStream(opts: SSEOptions = {}): SSEHandle {
  return useSSE('approvals', opts);
}
