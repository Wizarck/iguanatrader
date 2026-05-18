/**
 * Daemon status + toggle + reconcile client (slice ``dual-daemon-...``).
 *
 * Thin wrapper around `useFetch` returning either the typed DTO or an
 * RFC 7807 Problem. Callers pattern-match via `isProblem()` from the
 * useFetch composable.
 */

import { useFetch } from '$lib/composables/useFetch';
import type { Problem } from '$lib/types/problem';

import type {
  DaemonMode,
  DaemonReconcileOut,
  DaemonToggleIn,
  DaemonToggleOut,
  StatusResponse,
} from './types';

export function fetchStatus(): Promise<StatusResponse | Problem> {
  return useFetch<StatusResponse>('/api/v1/status');
}

export function toggleDaemon(
  mode: DaemonMode,
  payload: DaemonToggleIn,
): Promise<DaemonToggleOut | Problem> {
  return useFetch<DaemonToggleOut>(`/api/v1/daemons/${mode}/toggle`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function reconcileDaemon(mode: DaemonMode): Promise<DaemonReconcileOut | Problem> {
  return useFetch<DaemonReconcileOut>(`/api/v1/daemons/${mode}/reconcile`, {
    method: 'POST',
  });
}
