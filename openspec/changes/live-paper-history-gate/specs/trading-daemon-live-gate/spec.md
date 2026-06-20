## ADDED Requirements

### Requirement: Live startup enforces the paper-before-live override contract

The system SHALL gate the LIVE trading daemon's startup on paper-trading history per the AGENTS.md §7 override (2026-04-28). Paper trading SHALL always be recommended. Starting LIVE for a tenant with no recorded paper-trading history SHALL require BOTH `--confirm-live` and `--i-understand-the-risks` (or their env equivalents); when the acknowledgment is absent the system SHALL refuse to start (exit code 2) and SHALL NOT connect the broker. When paper-trading history exists for the tenant, `--confirm-live` alone SHALL suffice. Paper mode SHALL be unaffected.

#### Scenario: Live without paper history and without acknowledgment is blocked

- **GIVEN** the tenant has no `trading.daemon.session.started.paper` row in `audit_log`
- **WHEN** the daemon is started in LIVE mode with `--confirm-live` but without `--i-understand-the-risks` (and the env equivalent is unset)
- **THEN** the system exits with code 2, does not open a broker connection, and emits guidance to re-run with the acknowledgment flag

#### Scenario: Live with prior paper history needs only confirm-live

- **GIVEN** the tenant has a `trading.daemon.session.started.paper` row in `audit_log`
- **WHEN** the daemon is started in LIVE mode with `--confirm-live`
- **THEN** the paper-history gate passes without requiring `--i-understand-the-risks`

#### Scenario: Paper mode is not gated

- **WHEN** the daemon is started in paper mode
- **THEN** the paper-history gate is a no-op and writes no override row

### Requirement: Acknowledged live-without-history start warns and records the override

When LIVE is started for a tenant with no paper-trading history and the risk is acknowledged (flag or env), the system SHALL NOT block; it SHALL emit a WARNING carrying the risk-acknowledgment text and SHALL record the override decision in `audit_log` as event `trading.daemon.live_override.no_paper_history`, including the literal acknowledgment text.

#### Scenario: Acknowledged override proceeds and is recorded

- **GIVEN** the tenant has no paper-trading history
- **WHEN** the daemon is started in LIVE mode with `--confirm-live` and `--i-understand-the-risks`
- **THEN** the gate proceeds, a WARNING with the acknowledgment text is emitted, and an `audit_log` row with event `trading.daemon.live_override.no_paper_history` carrying that text is written

### Requirement: The daemon records a durable session-start audit row at boot

The system SHALL write an append-only `audit_log` row on every daemon boot with event `trading.daemon.session.started.{mode}` and `actor_kind = system`. The `.paper` variant SHALL be the signal a later LIVE start reads as paper-trading history.

#### Scenario: Paper boot writes the paper session marker

- **WHEN** the daemon boots in paper mode
- **THEN** an `audit_log` row with event `trading.daemon.session.started.paper` is committed for the tenant, and a subsequent LIVE start detects it as paper history
