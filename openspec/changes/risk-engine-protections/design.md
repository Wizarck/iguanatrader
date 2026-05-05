## Context

Slice K1 plants the **risk bounded context** — the non-bypassable gate every trade proposal MUST cross before reaching the approval channel (FR45 + FR11-FR18). Wave-2 cumulative state at K1 start:

- Wave 0 ✅ — monorepo, shared primitives (`IguanaError`, `Money`, `MessageBus`, `Port`), persistence + tenant listener.
- Wave 1 ✅ — JWT auth + dynamic-discovery API foundation + RFC 7807 + typegen pipeline.
- Wave 2 sibling **T1** (`trading-models-interfaces`) — defines `TradeProposal` model + `BrokerPort` / `StrategyPort` interfaces. K1's engine takes a `TradeProposal` as input; bridge contract enforces T1 merges before K1 so the FK target exists.

The engine is the heart of FR45. Architecture-decisions §47 mandates `RiskEngine.evaluate()` as **pure function**: input `(proposal, state, config)` → output `(allow / reject / clip)`. No I/O, no clock, no DB queries inside the engine — all dependencies pass-by-arg. This is what makes NFR-R6 (Hypothesis property tests covering arbitrary inputs) tractable: a pure function has no flakiness surface.

NFR-R5 (`<2s` kill-switch latency) is the second hard constraint. The kill-switch is a **flag polled in every hot-path operation**, not an async handler that could be queued behind other work. The persistence layout is dual: `kill_switch_state` (mutable single-row cache for sub-2s reads) backed by `kill_switch_events` (append-only authoritative log; the cached row is a fold of the events). Multiple activation sources (`file_flag`, `env_var`, `channel_command`, `dashboard_button`, `automatic_backoff`, `automatic_cap_breach`) all write to the same event log.

## Goals / Non-Goals

**Goals:**
- Plant the risk bounded context end-to-end: pure-functional engine + 5 protection callables + service orchestrator + repository + events + REST/SSE/CLI surfaces.
- Lock the cap-enforcement invariant via Hypothesis property test as a CI-blocking gate (NFR-R6).
- Persist every override decision with audit-quality metadata (`recorded_by + reason ≥20 chars + state_snapshot + confirmation_chain`).
- Expose a kill-switch lifecycle (activate / deactivate) with `<2s` latency from any activation source to first refused trade.
- Publish typed `risk.*` events on the MessageBus so approval (P1) + observability (O1) can subscribe without a code dependency on the risk module.

**Non-Goals:**
- No approval-channel command parsing — P1 owns Telegram/Hermes `/halt`, `/resume`, `/override` handlers; K1 only ships the underlying service methods + CLI equivalents.
- No per-tenant cap configuration UI — defaults are env-overridable Decimals; W1+ adds settings page later.
- No backtest-mode engine variant — the engine is mode-agnostic because it's pure; backtest replay lives in T3+.
- No ML-driven cap recommendations — caps are static Decimals per ADR.
- No risk-engine LLM observability hooks — engine makes zero LLM calls; cost-meter integration is N/A.

## Decisions

### D1. `RiskEngine.evaluate()` is a pure function — `(Proposal, State, Caps) → Decision`, no I/O

**Decision**: `apps/api/src/iguanatrader/contexts/risk/engine.py::evaluate(proposal: TradeProposal, state: RiskState, caps: RiskCaps) -> Decision` is a top-level function with no `self`, no DB access, no clock, no network. All dependencies are arguments. The `Decision` dataclass carries `outcome ∈ {allow, reject, clip}`, `cap_type_breached ∈ {None, per_trade, daily, weekly, max_open, max_drawdown}`, `current_pct: Decimal | None`, `clip_quantity: Decimal | None`, `state_snapshot: dict` (the `state` arg, snapshotted for audit).

**Alternatives considered**:
- **Class-based `RiskEngine` with injected `clock` + `repository`**: makes property testing harder (hypothesis would have to mock the clock + repo); muddles the "decision logic" from the "I/O orchestration". Rejected.
- **Async pure function** (`async def evaluate(...)`): no awaitable work inside — gratuitous async tax. Rejected.
- **Pure function but returning `tuple[Outcome, dict]` instead of a `Decision` dataclass**: less self-documenting; clients pattern-match on positional indices. Rejected.

**Rationale**: pure functions are property-testable trivially. NFR-R6 demands `hypothesis` covers arbitrary input combinations — a pure function has no setup/teardown, no flakiness from clock skew, no DB-state pollution between examples. The `service.py` orchestrator does the I/O (load state, persist evaluation, emit event); the engine just decides.

### D2. Each protection is a single-file pure-function module with the same `(Proposal, State, Caps) → Decision` signature

**Decision**: `apps/api/src/iguanatrader/contexts/risk/protections/{per_trade,daily,weekly,max_open,max_drawdown}.py` each export a single top-level callable `evaluate(proposal, state, caps) -> Decision`. The engine composes them in fixed order (per_trade → daily → weekly → max_open → max_drawdown) and returns the first non-`allow` decision (short-circuit semantics).

**Alternatives considered**:
- **Class-based `Protection(Protocol)` interface with implementations**: requires inheritance/protocol gymnastics for what is fundamentally a function. Rejected for ergonomics.
- **Single `protections.py` module with all 5 functions**: 5 files makes each protection independently testable + maintainable; one file becomes a 400-line grab-bag. Rejected.
- **Configurable order**: order is part of the FR45 contract; per-trade is cheapest to evaluate (single-trade cap), drawdown is most expensive (requires equity history). Fixed order documents intent. Rejected configurable.

**Rationale**: composability without inheritance. Adding a 6th protection in a future slice is "drop a file in `protections/` + add to engine's compose list"; that 1-line edit is the only shared-file touch. Each protection is unit-testable in isolation.

### D3. Caps are env-overridable `Decimal` constants with hardcoded MVP defaults — 2% / 5% / 15%

**Decision**: `apps/api/src/iguanatrader/contexts/risk/models.py::RiskCaps` is a frozen Pydantic v2 model with fields `per_trade_pct: Decimal = Decimal("0.02")`, `daily_loss_pct: Decimal = Decimal("0.05")`, `weekly_loss_pct: Decimal = Decimal("0.15")`, `max_open_positions: int = 10`, `max_drawdown_pct: Decimal = Decimal("0.15")`. Loaded by `service.py::_load_caps()` which reads env vars `IGUANATRADER_RISK_*` first, then falls back to defaults. Per-tenant overrides land in a future slice via `risk_caps` config row.

**Alternatives considered**:
- **YAML config file** (`config/risk.yaml`): adds a config-loading dependency; env vars are simpler for MVP + already used elsewhere.
- **Float caps**: violates the "Decimal everywhere for money" gotcha + ADR. Rejected.
- **Hardcoded only, no env override**: blocks operators from per-deployment tuning without redeploy. Rejected.

**Rationale**: matches the slice's stated "Caps por defecto: 2% per-trade, 5% daily, 15% max-drawdown" + integrates with the existing env-var pattern from slices 1-5. `Decimal` is non-negotiable per shared-primitives ADR. Per-tenant override is deferred — out of scope for K1 per `docs/openspec-slice.md`.

### D4. `kill_switch_events` is the source of truth; `kill_switch_state` is a denormalised cache

**Decision**: every kill-switch transition writes a row to `kill_switch_events` (append-only, immutable). The `kill_switch_state` row (one per tenant) is updated in the same transaction with `is_active` + `last_event_id`. A startup recovery routine recomputes `is_active` from the latest event if the cache row is missing or stale (e.g., after partial migration). Reads for the `<2s` NFR-R5 hot path go to `kill_switch_state` (single-row indexed lookup).

**Alternatives considered**:
- **Mutable row only, no event log**: loses the "who activated, when, why" audit trail. Rejected — FR29-FR30 explicitly require multi-source provenance.
- **Event log only, no cache**: every hot-path trade evaluation does an aggregation query over event history. Sub-2s achievable but unnecessarily expensive at scale. Rejected.
- **Cache the boolean in process memory** (`KILL_SWITCH_ACTIVE = True`): loses cross-process consistency (the daemon and the API are different processes); Litestream replication wouldn't carry the in-memory flag.

**Rationale**: documented in `docs/data-model.md §3.3` — append-only event log is authoritative, cached row is a fold for read latency. Same pattern as approval_decisions (P1) + audit_log (O1). NFR-R5 satisfied: a single-row index lookup is sub-millisecond on SQLite.

### D5. Override audit requires `recorded_by` (FK to `users.id`) + `reason_text ≥20 chars` + `confirmation_chain` JSONB — all mandatory

**Decision**: `risk_overrides` table has a CHECK constraint `length(reason_text) >= 20` (per NFR-S5 + FR25's "≥20 chars"); `authorised_by_user_id` is `NOT NULL FK ON DELETE RESTRICT` (the user who authorised the override cannot be deleted while the override exists); `confirmation_chain` JSONB stores the double-confirmation chain (first/second confirmations + timestamps + channels) per FR25's "double confirmation" requirement. The service-layer method `record_override(...)` raises `OverrideAuditMissingError` if any field is empty/short before persistence.

**Alternatives considered**:
- **`reason_text` optional**: violates FR25's mandatory-reason contract. Rejected.
- **No DB-level CHECK, application-level only**: defence-in-depth says both. CHECK at the DB level is the last-line guarantee. Kept both.
- **Confirmation chain as separate table**: over-engineered for MVP; JSONB is sufficient + queryable in PostgreSQL (and SQLite via `json_extract`).

**Rationale**: this is a critical audit table — `iguana export risk-overrides` (NFR-O5) reads it for weekly review, regulators MAY want it (we're not regulated yet but it's cheap to be compliant-ready). Mandatory fields enforced at three layers (Pydantic DTO validation → service-layer `OverrideAuditMissingError` → DB CHECK).

### D6. Cross-context contract: typed `risk.*` events on the MessageBus, not direct module imports

**Decision**: `events.py` declares Pydantic event payloads `RiskProposalAccepted`, `RiskProposalRejected`, `RiskProposalOverrideRequired`, `RiskKillSwitchActivated`, `RiskKillSwitchDeactivated`. Service-layer methods publish to the MessageBus via slice 2's `MessageBus.publish(channel, event)` with channel names `risk.proposal.accepted`, `risk.proposal.rejected`, `risk.proposal.override_required`, `risk.kill_switch.activated`, `risk.kill_switch.deactivated`. Approval (P1) + observability (O1) subscribe; they NEVER `from iguanatrader.contexts.risk import ...` directly.

**Alternatives considered**:
- **Direct module imports between contexts**: violates the bounded-context boundary; couples P1 + O1 to risk's internal module layout. Rejected per architecture-decisions §59.
- **Untyped event payloads (dict)**: subscribers have to defensively parse; type drift inevitable. Rejected.
- **Synchronous callbacks instead of MessageBus**: blocks the trade-evaluation hot path on subscriber latency; defeats the loose-coupling intent. Rejected.

**Rationale**: bounded contexts publish events; other contexts subscribe. The MessageBus is the only cross-context surface (per slice 2's contract). Frontend consumes via `/stream/risk/events` SSE which the route handler bridges from the MessageBus channel.

### D7. Hypothesis property test as CI-blocking gate — 200 examples, deadline=None, asserts cap-never-breached invariant

**Decision**: `apps/api/tests/property/test_risk_caps_invariant.py` defines `@given(proposal=proposal_strategy(), state=state_strategy(), caps=caps_strategy())` with `@settings(max_examples=200, deadline=None)`. Test body: call `engine.evaluate(proposal, state, caps)`; if `decision.outcome == "allow"`, compute the post-trade cap utilisation (per_trade, daily, weekly, max_open, max_drawdown) and `assert` each is `<= caps.<corresponding_field>`. Counterexamples shrink to minimal failing inputs. Test is in `tests/property/` so the existing CI workflow's `pytest tests/property/` selector picks it up; `pytest.ini` markers `property` + `ci_blocking` make the gate explicit.

**Alternatives considered**:
- **`max_examples=1000`**: stronger guarantee but slower CI (each example is microseconds since engine is pure, but 1000 examples × 5 protections still adds up). 200 is the existing convention from slice 2's property tests. Stay consistent.
- **`deadline=200ms` (default)**: hypothesis flags slow examples as timing-flaky; the engine is microsecond-scale but CI runners can hiccup. `deadline=None` per the slice-2 convention.
- **Test as advisory (warn-only)**: NFR-R6 says CI-blocking. No backsliding.
- **Generate proposals from real historical data**: out of scope for K1; engine is pure so synthetic Hypothesis inputs cover the space.

**Rationale**: NFR-R6 is the contract. The property test is the only proof that no input combination breaches the caps; without it, the engine's correctness is "spot-checked at most." Hypothesis shrinking gives operators a minimal counterexample if a future refactor breaks the invariant — debugging is fast.

## Risks / Trade-offs

- **[Risk] Engine purity violated by an over-eager refactor** (e.g., a future slice adds a `service.evaluate()` shortcut that calls a clock for "stale state detection") → cascades into property-test flakiness because hypothesis can't control the clock. **Mitigation**: a unit test `test_engine_purity.py` introspects the engine module via `inspect.getsource` + AST + asserts no `import datetime`, no `time.`, no `.now()`, no `requests`, no `sqlalchemy`. CI fails fast on impurity regression.

- **[Risk] Kill-switch cache row drifts from event log** (e.g., a partial migration writes the event but skips the cache update) → reads return stale `is_active`. **Mitigation**: same-transaction write of both rows; the `service.py::activate_kill_switch` method wraps both INSERT (event) + UPDATE (state) in a single SQLAlchemy session.commit(); a startup recovery routine recomputes the cache from the event log if the `last_event_id` doesn't match the latest event row.

- **[Risk] `risk_overrides.reason_text` 20-char floor is satisfiable with `"aaaaaaaaaaaaaaaaaaaa"`** → operators game the field with junk to bypass the audit. **Mitigation**: out of scope for K1 (PRD's NFR-S5 says ≥20 chars, no semantic check). Future slice can add LLM-judged reason quality; for now, weekly-review humans flag junk reasons during retrospectives.

- **[Risk] Hypothesis property test takes >30s on slow CI runners** → developers tempted to mark `@pytest.mark.skip` to "fix CI." **Mitigation**: `deadline=None` means individual example timeouts don't fail; total wall-clock is bounded by `max_examples=200 × O(microseconds) ≈ <1s typical`. Document in `docs/gotchas.md`: skipping the property test fails the `ai-self-review-required` gate; reviewers must flag.

- **[Risk] T1 merge slips past K1 propose stage** → K1's migration FK to `trade_proposals.id` won't apply cleanly. **Mitigation**: K1 documents the bridge contract in proposal.md "Prerequisites"; PR template asks "T1 already merged?" as a gate; if T1 is delayed, K1 can be merged with the FK marked deferred (Alembic migration adds the FK in a `0004b_risk_fk.py` follow-up after T1 lands).

- **[Trade-off] Pure-functional engine means state-loading + persistence are split across `service.py`** — readers have to follow two files to understand "what happens when a proposal is evaluated." Documented in `contexts/risk/__init__.py` docstring + reinforced in code review. The win (property-testability) is worth the indirection.

- **[Trade-off] Kill-switch cache `is_active` boolean doesn't carry "why activated" — readers must JOIN to `kill_switch_events.last_event_id` to see source/reason. Acceptable: the hot path only needs the boolean; audit consumers do the JOIN.

## Migration Plan

This slice has no live deployment to migrate from. Deployment path:

1. T1 (`trading-models-interfaces`) merges first — `trade_proposals.id` exists.
2. K1 merges; Alembic migration `0004_risk_tables.py` runs, creating the 4 risk tables.
3. The dynamic-discovery loop picks up `routes/risk.py` + `sse/risk.py` + `cli/ops.py` automatically — no `app.py` or `cli/main.py` edits.
4. P1 (later in Wave 2) wires Telegram/Hermes commands to `risk_service.activate_kill_switch(source="channel_command", ...)`.
5. O1 subscribes to `risk.*` MessageBus channels for cost-dashboard / audit log emission.

Rollback: revert PR + Alembic downgrade `0004 → 0003`. The downgrade drops the 4 risk tables; no data loss in dev/staging because no production deployment yet.

## Open Questions

- **Q**: Does `risk_overrides.confirmation_chain` JSONB schema get a Pydantic model (`ConfirmationChain`) in `dtos/risk.py`, or stay loose `dict`? **Tentative answer**: yes, typed Pydantic model with `first_confirmation: Confirmation` + `second_confirmation: Confirmation` (each carrying `channel`, `at`, `actor_user_id`). The DTO validation gives the API layer a schema; the JSONB column stores the model_dump() output.

- **Q**: Should the `cli/ops.py` `halt` command write an event with `source="channel_command"` or a new `source="cli"` value? **Tentative answer**: extend the CHECK constraint to include `'cli'` — the data-model.md §3.3 list (`file_flag, env_var, channel_command, dashboard_button, automatic_backoff, automatic_cap_breach`) is missing `cli`. Migration 0004 adds `'cli'` to the CHECK; documented as a slice-K1 spec deviation.

- **Q**: Property test should run against `RiskEngine.evaluate` only, or also exercise each protection in isolation? **Tentative answer**: both. The CI-blocking invariant test uses the composed engine (the FR45 contract); per-protection unit tests in `tests/unit/contexts/risk/test_protections.py` give faster feedback during dev.
