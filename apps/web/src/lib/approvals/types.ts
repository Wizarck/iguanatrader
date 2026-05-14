/**
 * Frontend mirrors of the FastAPI Pydantic DTOs in
 * `apps/api/src/iguanatrader/api/dtos/approvals.py`.
 *
 * Same shape contract as `$lib/strategies/types.ts` + `$lib/trades/types.ts`:
 * UUIDs as strings, timestamps as ISO 8601 strings, Pydantic dicts as
 * `Record<string, unknown>` (we never read into them on the frontend in v1).
 */

export type ApprovalRequest = {
  id: string;
  tenant_id: string;
  proposal_id: string;
  delivered_to_channels: string[];
  timeout_seconds: number;
  expires_at: string;
  created_at: string;
  delivery_failures: Record<string, unknown>[] | null;
};

export type ApprovalOutcome = 'granted' | 'rejected' | 'timeout';

export type ApprovalDecidedViaChannel =
  | 'telegram'
  | 'whatsapp'
  | 'dashboard'
  | 'timeout'
  | 'system';

export type ApprovalDecision = {
  id: string;
  tenant_id: string;
  request_id: string;
  outcome: ApprovalOutcome;
  decided_via_channel: ApprovalDecidedViaChannel;
  decided_by_user_id: string | null;
  decided_by_sender_id: string | null;
  latency_ms: number;
  created_at: string;
};

export type ApprovalCommandStatus = 'ok' | 'denied' | 'unknown_command' | 'error';

export type ApprovalCommandResult = {
  status: ApprovalCommandStatus;
  message: string;
  extra: Record<string, unknown> | null;
};

export type RejectionRequest = {
  reason: string | null;
};
