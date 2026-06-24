## 1. Paper-history detection

- [x] 1.1 `AuditLogRepository.event_exists(event)` — tenant-scoped existence check (explicit `tenant_id` predicate on top of the scoping listener).
- [x] 1.2 Daemon writes a durable session-start row on every boot: `trading.daemon.session.started.{mode}` (actor_kind `system`), via `_record_daemon_session_start`.

## 2. Live gate

- [x] 2.1 New CLI flag `--i-understand-the-risks` (+ env `IGUANATRADER_I_UNDERSTAND_THE_RISKS`), threaded into `_run_daemon`.
- [x] 2.2 `_enforce_live_paper_history_gate`: no-op for paper; pass for live with prior paper history; block (exit 2) for live without history when unacknowledged; WARNING + recorded override for live without history when acknowledged.
- [x] 2.3 Gate runs BEFORE `_build_broker` (no real-money socket opened on a blocked start), inside a short-lived session + tenant scope.
- [x] 2.4 Override decision recorded in `audit_log` (`trading.daemon.live_override.no_paper_history`) with the literal risk-acknowledgment text.

## 3. Validation & gate

- [x] 3.1 Helper-level tests (DB-free, fake audit repo): paper no-op; live+history pass; live no-history block; live no-history acknowledged (flag and env) → override recorded; session-start writes the mode-tagged event.
- [x] 3.2 Existing synchronous `--confirm-live` CliRunner tests stay green.
- [x] 3.3 ruff green on touched files; `openspec validate live-paper-history-gate --strict` passes.
