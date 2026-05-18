/**
 * Daemon status DTO mirrors (slice ``dual-daemon-mode-toggle-and-reconcile``).
 *
 * Wire-format types matching the FastAPI Pydantic DTOs at
 * `apps/api/src/iguanatrader/api/dtos/status.py`. Kept in sync manually
 * for now; once the openapi.json -> packages/shared-types regen lands
 * for this slice these can be re-exported from there instead.
 */

export type DaemonMode = 'paper' | 'live';

export interface DaemonStatusOut {
  mode: DaemonMode;
  enabled: boolean;
  ib_connected: boolean;
  last_heartbeat_at: string | null;
  last_fill_at: string | null;
  pending_proposals_count: number;
}

export interface StatusResponse {
  daemons: DaemonStatusOut[];
  fetched_at: string;
}

export interface DaemonToggleIn {
  enabled: boolean;
  reason?: string | null;
  password_reconfirm?: string | null;
}

export interface DaemonToggleOut {
  mode: DaemonMode;
  enabled: boolean;
  last_toggled_at: string;
  reason: string | null;
}

export interface DaemonReconcileOut {
  mode: DaemonMode;
  correlation_id: string;
  accepted_at: string;
}
