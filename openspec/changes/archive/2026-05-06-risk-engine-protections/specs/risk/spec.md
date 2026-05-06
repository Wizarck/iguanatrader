## ADDED Requirements

### Requirement: `RiskEngine.evaluate()` is a pure function with no I/O

The system SHALL expose `iguanatrader.contexts.risk.engine.evaluate(proposal: TradeProposal, state: RiskState, caps: RiskCaps) -> Decision` as a top-level function with no I/O dependencies — no database access, no clock reads, no network calls, no file-system access. All inputs SHALL be passed as arguments; all outputs SHALL be encoded in the returned `Decision` dataclass. The function SHALL be deterministic: identical inputs SHALL produce identical outputs.

#### Scenario: Engine called with a passing proposal returns allow decision

- **WHEN** `evaluate(proposal, state, caps)` is called with a proposal whose post-trade utilisation falls below every cap in `caps`
- **THEN** the returned `Decision` has `outcome="allow"`, `cap_type_breached=None`, and `state_snapshot` mirrors the input `state`
- **AND** no exceptions are raised
- **AND** the function call completes without any I/O side effect (verified by purity unit test)

#### Scenario: Engine purity verified by static analysis

- **WHEN** the test `test_engine_purity.py` inspects the `engine.py` source via AST
- **THEN** the AST contains no `import datetime`, no `import time`, no `from time import`, no `requests`, no `httpx`, no `sqlalchemy` imports
- **AND** no function call to `.now()`, `.utcnow()`, `.commit()`, `.execute()`, `.add()`, `.delete()`
- **AND** the test fails the build if any forbidden symbol is detected

### Requirement: Per-trade cap rejects proposals exceeding 2% of capital by default

The system SHALL enforce a per-trade cap defaulting to 2% of capital (`RiskCaps.per_trade_pct = Decimal("0.02")`). Any proposal whose `notional_value / capital` strictly exceeds the cap SHALL produce `Decision(outcome="reject", cap_type_breached="per_trade", current_pct=<computed>)`. The cap SHALL be overridable via environment variable `IGUANATRADER_RISK_PER_TRADE_PCT`.

#### Scenario: Proposal at 2.5% notional rejected with per-trade breach

- **WHEN** `evaluate(proposal, state, caps)` is called with `proposal.notional_value=Decimal("2500")`, `state.capital=Decimal("100000")`, `caps.per_trade_pct=Decimal("0.02")`
- **THEN** the returned `Decision` has `outcome="reject"`, `cap_type_breached="per_trade"`, `current_pct=Decimal("0.025")`
- **AND** the rejection reason is renderable as a human-readable string in `service.py` for downstream events / logs
- **AND** no later protection (daily, weekly, max_open, max_drawdown) is evaluated (short-circuit semantics)

### Requirement: Daily-loss cap rejects proposals when day-to-date loss is at-or-above 5%

The system SHALL enforce a daily-loss cap defaulting to 5% (`RiskCaps.daily_loss_pct = Decimal("0.05")`). When `state.day_to_date_loss_pct >= caps.daily_loss_pct`, the engine SHALL return `Decision(outcome="reject", cap_type_breached="daily")` for ALL incoming proposals (not just losing ones — the cap is a daily blanket halt). The cap SHALL be overridable via `IGUANATRADER_RISK_DAILY_LOSS_PCT`. Service-layer SHALL emit `risk.kill_switch.activated` with `source="automatic_cap_breach"` when this threshold is first crossed in a day.

#### Scenario: Day-to-date loss at 5.1% halts new proposals

- **WHEN** `evaluate(proposal, state, caps)` is called with `state.day_to_date_loss_pct=Decimal("0.051")` and `caps.daily_loss_pct=Decimal("0.05")`
- **THEN** the returned `Decision` has `outcome="reject"`, `cap_type_breached="daily"`
- **AND** the service-layer caller (on first observed daily breach of the calendar day) writes `kill_switch_events(transition="activated", source="automatic_cap_breach")` AND publishes `risk.kill_switch.activated` event
- **AND** subsequent same-day proposals are rejected at the kill-switch gate before even reaching the engine

### Requirement: Max-drawdown cap rejects proposals when peak-to-trough drawdown is at-or-above 15%

The system SHALL enforce a max-drawdown cap defaulting to 15% (`RiskCaps.max_drawdown_pct = Decimal("0.15")`). When `state.peak_to_trough_drawdown_pct >= caps.max_drawdown_pct`, the engine SHALL return `Decision(outcome="reject", cap_type_breached="max_drawdown")`. This is the ultimate circuit-breaker beyond daily/weekly losses. The cap SHALL be overridable via `IGUANATRADER_RISK_MAX_DRAWDOWN_PCT`.

#### Scenario: 15.5% drawdown locks out all new trades

- **WHEN** `evaluate(proposal, state, caps)` is called with `state.peak_to_trough_drawdown_pct=Decimal("0.155")` and `caps.max_drawdown_pct=Decimal("0.15")`
- **THEN** the returned `Decision` has `outcome="reject"`, `cap_type_breached="max_drawdown"`
- **AND** the service-layer caller activates the kill-switch with `source="automatic_cap_breach"`
- **AND** the kill-switch SHALL remain active until an admin operator explicitly resumes via `iguanatrader ops resume --reason "..."` (FR30 — refuses execution while kill-switch active)

### Requirement: Kill-switch activation propagates to first refused trade in under 2 seconds

The system SHALL activate the kill-switch from any of six sources (`file_flag`, `env_var`, `channel_command`, `dashboard_button`, `automatic_backoff`, `automatic_cap_breach`, plus `cli` for K1's CLI ops commands) and SHALL refuse subsequent trade-evaluation requests within 2 seconds of activation (NFR-R5). The kill-switch state SHALL be persisted via `kill_switch_events` (append-only log) + `kill_switch_state` (cached row updated in the same transaction).

#### Scenario: CLI halt propagates to next evaluate() call within 2s

- **WHEN** `iguanatrader ops halt --reason "Manual freeze: market dislocation"` is executed at `t=0`
- **AND** a new `evaluate(proposal, state, caps)` is invoked at `t=0+1s` via the trading service
- **THEN** the kill-switch gate in `service.py::evaluate_proposal` reads `kill_switch_state.is_active=True` and rejects the proposal with `KillSwitchActiveError` BEFORE the engine is called
- **AND** the integration test `test_kill_switch_latency.py` asserts the activation-to-refusal wall-clock latency is under 2000ms

#### Scenario: Multi-source activation idempotent

- **WHEN** the kill-switch is already active (last event `transition="activated"`)
- **AND** a second activation arrives from a different source (e.g., `dashboard_button` after `cli`)
- **THEN** a second `kill_switch_events` row is appended (audit preserves all activation attempts)
- **AND** `kill_switch_state.is_active` remains `True` (idempotent on the cached state)
- **AND** `risk.kill_switch.activated` is NOT re-published (deduplicated at service layer)

### Requirement: Override audit requires `recorded_by` (user FK) + `reason_text ≥20 chars` + `confirmation_chain` JSONB — all mandatory

The system SHALL persist every risk override to `risk_overrides` with `authorised_by_user_id` (FK to `users.id`, NOT NULL, ON DELETE RESTRICT), `reason_text` (NOT NULL, CHECK `length(reason_text) >= 20` per NFR-S5 + FR25), and `confirmation_chain` (NOT NULL JSONB carrying first/second confirmations + timestamps + channels per FR25's double-confirmation requirement). The service-layer `record_override(...)` method SHALL raise `OverrideAuditMissingError` (a `ValidationError` subclass) before persistence if any field is missing, empty, or fails the 20-char minimum.

#### Scenario: Override with 19-char reason rejected at service layer

- **WHEN** `risk_service.record_override(proposal_id=..., user_id=..., reason_text="Need to bypass cap", confirmation_chain=...)` is called (reason is 18 chars)
- **THEN** `OverrideAuditMissingError` is raised before any DB write
- **AND** the global RFC 7807 handler renders `{"type": "urn:iguanatrader:error:validation", "title": "Validation Failed", "status": 400, "detail": "reason_text must be at least 20 characters", "errors": [{"field": "reason_text", "code": "min_length", "detail": "..."}]}`
- **AND** no `risk_overrides` row is created

#### Scenario: Valid override persisted with full audit metadata

- **WHEN** `risk_service.record_override(proposal_id=<uuid>, user_id=<uuid>, reason_text="Earnings beat justifies 3.5% allocation; daily cap untouched.", confirmation_chain={"first": {...}, "second": {...}})` is called
- **THEN** a single `risk_overrides` row is INSERTed with `authorised_by_user_id`, `reason_text`, `confirmation_chain`, `state_snapshot_at_override`, `created_at`
- **AND** the linked `risk_evaluations` row remains untouched (append-only — overrides do not mutate the original evaluation)
- **AND** the event `risk.proposal.override_required` (with `RiskOverrideRecorded` follow-up payload) is published to the MessageBus
- **AND** the same row is returnable via `GET /api/v1/risk/overrides?proposal_id=<uuid>` for audit consumers

### Requirement: Hypothesis property test enforces caps invariant as CI-blocking gate

The system SHALL provide a Hypothesis property test `apps/api/tests/property/test_risk_caps_invariant.py` that generates arbitrary `(proposal, state, caps)` triples and asserts: for every triple where `engine.evaluate(...).outcome == "allow"`, the post-trade cap utilisation across all five cap types SHALL be at-or-below the corresponding cap value in `caps`. The test SHALL run with `@settings(max_examples=200, deadline=None)`. CI SHALL fail the build on any counterexample (NFR-R6, marked `@pytest.mark.property` + `@pytest.mark.ci_blocking`).

#### Scenario: Property test runs in CI on every push

- **WHEN** a developer pushes a commit to a `slice/**` or `feat/**` branch
- **AND** the GitHub Actions `ci.yml` workflow's `pytest tests/property/` job runs
- **THEN** `test_risk_caps_invariant.py` executes 200 examples
- **AND** the workflow exits non-zero (build fails) if any example violates the invariant
- **AND** Hypothesis prints the shrunk minimal counterexample in CI logs for debugging

#### Scenario: Property test counterexample shrinks to minimal failing input

- **WHEN** a regression in `engine.py` lets a 2.001% per-trade proposal slip through with `outcome="allow"`
- **THEN** Hypothesis shrinks the failing input to the smallest `(proposal, state, caps)` that still triggers the violation
- **AND** the shrunk example is printed in test output as `proposal=<...>, state=<...>, caps=<...>`
- **AND** the test fails with the assertion `post_trade_per_trade_pct (0.02001) > caps.per_trade_pct (0.02)`
