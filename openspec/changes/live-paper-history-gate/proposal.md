## Why

Audit finding **#15** (residual after the PR #283/#285/#289 remediation wave): the live trading daemon's startup gate enforces only `--confirm-live`. The AGENTS.md §7 override contract (2026-04-28) requires more: paper trading is ALWAYS recommended, and starting LIVE for a tenant with **no recorded paper-trading history** must require BOTH `--confirm-live` AND `--i-understand-the-risks`, must emit a WARNING with risk-acknowledgment text (it does not block once acknowledged), and must record the override decision in `audit_log`. Today there is no second flag, no paper-history check, and the daemon writes nothing to `audit_log` at boot — so the "absence of a paper-trading record" the contract hinges on can never be detected.

## What Changes

- The daemon writes a durable **session-start `audit_log` row** on every boot: event `trading.daemon.session.started.{mode}` (the `.paper` variant is what a later LIVE start reads as paper history). This also satisfies the "immutable execution logs" hard rule for daemon lifecycle.
- New CLI flag `--i-understand-the-risks` (env `IGUANATRADER_I_UNDERSTAND_THE_RISKS`). Required, together with `--confirm-live`, ONLY when starting LIVE for a tenant with no prior paper-trading record.
- The **paper-history gate** runs BEFORE the broker connects (so a blocked LIVE start never opens a real-money socket):
  - paper mode → no-op;
  - LIVE with prior paper history → `--confirm-live` alone suffices;
  - LIVE without paper history and unacknowledged → block (exit 2) with guidance;
  - LIVE without paper history and acknowledged → WARNING + an `audit_log` override row (`trading.daemon.live_override.no_paper_history`) carrying the literal acknowledgment text.
- `AuditLogRepository.event_exists(event)` — tenant-scoped existence check backing the gate.
- **NOT** changing: the existing synchronous `--confirm-live` gate (kept, fast-fail), the dual-daemon DB-poll comms, or any order/execution path.

## Capabilities

### New Capabilities
- `trading-daemon-live-gate`: the live-daemon startup gate enforces the AGENTS.md §7 paper-before-live override contract — paper-history detection via `audit_log`, a second acknowledgment flag required only without paper history, a non-blocking WARNING, and a durable recorded override.

### Modified Capabilities
(none — no archived spec capability changes its requirements)

## Impact

- **Code**: `apps/api/src/iguanatrader/cli/trading.py` (flag + gate helpers + boot session-start record), `contexts/observability/repository.py` (`event_exists`).
- **Hard rules**: honours the §7 override contract (recommendation invariant) and the immutable-execution-logs rule (append-only `audit_log` boot rows); no change to the kill-switch or capital caps.
- **Tests**: `tests/unit/cli/test_trading_live_gate.py` — gate helper matrix (paper no-op; live+history pass; live no-history block; live no-history acknowledged → override recorded; env acknowledgment) + the existing CliRunner gate tests stay green.
- **Config**: `IGUANATRADER_I_UNDERSTAND_THE_RISKS` env (optional; flag equivalent). No secrets, no new dependencies.
