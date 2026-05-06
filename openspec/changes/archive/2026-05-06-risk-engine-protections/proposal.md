## Why

Slice K1 (`risk-engine-protections`) is the Wave-2 risk bounded context. The PRD pipeline `Strategy → RiskEngine → ApprovalChannel → BrokerInterface` (FR45 + FR11-FR18) is non-bypassable: every proposal MUST pass risk evaluation before it can reach the approval channel (FR24). Without K1, T1's `trade_proposals` would have nowhere to go — `service.py` already wires `propose → risk_check → enqueue_approval` and that hop has to land. NFR-R5 demands `<2s` kill-switch latency from activation to first refused trade; NFR-R6 demands a CI-blocking property test that proves the `RiskEngine` never lets any proposal through that would breach the configured caps. The slice is also the home of the override audit chain (FR25-FR26) — overrides must be persisted with `recorded_by + reason ≥20 chars + state snapshot` so weekly reviews can reconstruct every "I bypassed the cap" decision. Wave 2 reads T1's `trade_proposals` table; the bridge merges T1 → K1 so T1's foreign-key targets exist before K1's `risk_evaluations.proposal_id` FK is added. Now is the right time because slice 5 (`api-foundation-rfc7807`) just shipped the dynamic-discovery contract — K1 is the first risk-domain slice that exercises `routes/risk.py` + `sse/risk.py` + `cli/ops.py` without editing `app.py` or `cli/main.py`.

## What Changes

- **Bounded context `risk` planted complete** — `apps/api/src/iguanatrader/contexts/risk/{__init__,models,ports,engine,service,repository,events}.py` plus `protections/{per_trade,daily,weekly,max_open,max_drawdown}.py`. The engine is a pure function `(Proposal, State, Caps) → Decision` (no I/O, no DB, no clock, no network — all dependencies pass-by-arg). Each protection is a single-file callable with the same signature, composed by the engine.
- **5 protections at default caps** — `per_trade` (2% of capital), `daily` (5% drawdown kill-switch), `weekly` (15% drawdown), `max_open` (max open positions), `max_drawdown` (15% peak-to-trough kill-switch). Caps are env-overridable `Decimal` constants per ADR + gotchas convention; per-tenant overrides land via `risk_caps` config row in T1+ (out of scope for K1).
- **Migration `0004_risk_tables.py`** — `risk_evaluations` (append-only, `outcome ∈ {allow, reject, clip}`, `cap_type_breached`, `state_snapshot` JSONB), `risk_overrides` (append-only audit, FK to `users.id`, `reason_text` ≥20 chars CHECK, `confirmation_chain` JSONB, `state_snapshot_at_override`), `kill_switch_state` (single mutable row per tenant, cached materialisation), `kill_switch_events` (append-only authoritative log, `transition ∈ {activated, deactivated}`, `source ∈ {file_flag, env_var, channel_command, dashboard_button, automatic_backoff, automatic_cap_breach}`).
- **Service + repository** — `service.py` orchestrates `evaluate_proposal(proposal) → RiskEvaluation` (calls engine, persists to `risk_evaluations`, emits `risk.proposal.{accepted,rejected}` event), `record_override(...)`, `activate_kill_switch(...)`, `deactivate_kill_switch(...)`. `repository.py` wraps SQLAlchemy queries; uses tenant-scoped queries via slice 3's `tenant_id_var`.
- **Cross-context events** — `events.py` declares the typed Pydantic event payloads consumed by approval (P1) + observability (O1): `risk.proposal.accepted`, `risk.proposal.rejected`, `risk.proposal.override_required`, `risk.kill_switch.activated`, `risk.kill_switch.deactivated`. Published via slice 2's `MessageBus`.
- **API surface** — `api/routes/risk.py` ships `GET /api/v1/risk/state` (current caps + utilisation + kill-switch flag) + `POST /api/v1/risk/override` (admin-only, requires `recorded_by + reason ≥20 chars`, persists to `risk_overrides`). `api/sse/risk.py` ships `/api/v1/stream/risk/events` for live decision feed (consumed by W1 dashboard). `api/dtos/risk.py` declares the Pydantic payloads (RFC 7807 errors via slice 5's global handler).
- **CLI ops** — `cli/ops.py` exports `app: typer.Typer` with three commands: `iguanatrader ops halt --reason "..."` (writes `kill_switch_events` row), `iguanatrader ops resume --reason "..."`, `iguanatrader ops override --proposal-id <uuid> --reason "..."` (audit-trail entry). Discovered automatically by slice 5's `cli/main.py` loop.
- **CI-blocking property test** — `apps/api/tests/property/test_risk_caps_invariant.py` uses Hypothesis to generate arbitrary proposal sequences against arbitrary state snapshots; the engine MUST never produce `outcome="allow"` whose post-trade cap utilisation would breach 2/5/15. 200 examples, deadline=None, marked `@pytest.mark.property`. Workflow `.github/workflows/ci.yml` already runs `pytest tests/property/` — this slice ensures the new test joins that selector AND fails the build on any counterexample (NFR-R6).
- **No frontend consumption** — W1 ships the dashboard skeleton; the risk page is a `"loading…"` placeholder until W2-equivalent slice. K1 just ensures the SSE feed + REST endpoints exist so W1's stub can connect.

## Capabilities

### New Capabilities

- `risk`: bounded context implementing the FR19-FR30 cap enforcement + override audit + kill-switch lifecycle. The pure-functional engine is property-tested as an NFR-R6 CI gate; the kill-switch event log + cached state row are the NFR-R5 sub-2s-latency mechanism. Cross-context contract: `risk.*` events on the MessageBus + `GET /risk/state` + `POST /risk/override` REST + `/stream/risk/events` SSE.

### Modified Capabilities

(none — `api-foundation` slice 5's contract is consumed unchanged; the new `routes/risk.py` + `sse/risk.py` + `cli/ops.py` modules plug into the existing dynamic-discovery loops with zero edits to shared registry files.)

## Impact

- **Affected code (slice-K1-owned, write-allowed)**:
  - `apps/api/src/iguanatrader/contexts/risk/__init__.py` (NEW) — public API: `RiskService`, `RiskEngine`, `Decision`, `Protection`.
  - `apps/api/src/iguanatrader/contexts/risk/{models,ports,engine,service,repository,events}.py` (NEW) — bounded context skeleton.
  - `apps/api/src/iguanatrader/contexts/risk/protections/{__init__,per_trade,daily,weekly,max_open,max_drawdown}.py` (NEW) — 5 pure-function protections.
  - `apps/api/src/iguanatrader/migrations/versions/0004_risk_tables.py` (NEW) — Alembic migration adds the 4 risk tables with constraints.
  - `apps/api/src/iguanatrader/api/routes/risk.py` (NEW) — `GET /risk/state` + `POST /risk/override`.
  - `apps/api/src/iguanatrader/api/sse/risk.py` (NEW) — `/stream/risk/events`.
  - `apps/api/src/iguanatrader/api/dtos/risk.py` (NEW) — Pydantic DTOs for the routes + SSE.
  - `apps/api/src/iguanatrader/cli/ops.py` (NEW) — `halt` / `resume` / `override` commands.
  - `apps/api/tests/property/test_risk_caps_invariant.py` (NEW) — Hypothesis CI-blocking gate.
  - `apps/api/tests/integration/test_risk_engine_flow.py` (NEW) — happy + reject + override paths.
  - `apps/api/tests/integration/test_kill_switch_latency.py` (NEW) — NFR-R5 sub-2s assertion.
  - `apps/api/tests/unit/contexts/risk/{test_protections,test_engine_purity}.py` (NEW) — unit-level coverage of each protection.
- **Affected code (slice-2/3/4/5/T1-owned, read-only consumed)**:
  - `iguanatrader.shared.{kernel,types,errors,messagebus,ports}` (slice 2) — Money, IguanaError hierarchy, MessageBus, Port protocol.
  - `iguanatrader.persistence.{models,append_only_listener}` (slice 3) — base SQLAlchemy + tenant scoping.
  - `iguanatrader.api.errors` + `api.dtos.common.Problem` (slice 5) — global RFC 7807 handler renders all `IguanaError` subclasses.
  - `iguanatrader.contexts.trading.models.TradeProposal` (T1 — merged before K1 per Wave-2 bridge) — engine input type.
- **Affected APIs**: 2 new REST + 1 new SSE endpoint family. All errors render RFC 7807 via slice 5's global handler — `RiskCapBreachedError`, `KillSwitchActiveError`, `OverrideAuditMissingError` are new `IguanaError` subclasses added to `shared/errors.py` with canonical `urn:iguanatrader:error:risk-*` type URIs.
- **Affected dependencies**: `hypothesis>=6.100,<7.0` already in dev deps from slice 2's property tests; verify pin range covers K1 usage. No new runtime deps.
- **Prerequisites**: `api-foundation-rfc7807` (slice 5) for dynamic discovery + RFC 7807 + DTO common types. **Cross-ref T1 (`trading-models-interfaces`)**: K1's `risk_evaluations.proposal_id` FK references T1's `trade_proposals.id`; merge order T1 → K1 enforced by Wave-2 bridge contract (per `docs/openspec-slice.md`). If T1's openspec dir is unavailable at K1 propose time, K1 still scaffolds against the documented `TradeProposal` shape in `docs/data-model.md §3.2`.
- **Capability coverage** (per `docs/openspec-slice.md` row K1): FR19-FR30 + NFR-R5 (kill-switch <2s) + NFR-R6 (property-tested caps). Migration number 0004 (slice 1=0001, slice 3=0002, slice 4=0003-equivalent in archive — verify monotonic at PR time).
- **Out of scope** (per `docs/openspec-slice.md` row K1):
  - Per-tenant cap configuration UI — surfaces in W1+ settings page.
  - Approval channel command handling (`/halt`, `/resume`, `/override` as Telegram/Hermes commands) — slice P1 owns the channel handler; K1 only ships the CLI variants + the underlying service methods that P1's command_handler will call.
  - Observability cost-meter wiring of risk-engine LLM calls — engine is pure-functional, makes no LLM calls; out of scope.
  - SvelteKit risk page content — W1 stubs; W2-equivalent slice fills.
  - Backtest-mode risk engine variant (e.g., historical state replay) — engine is mode-agnostic by virtue of being pure; backtest harness lives in T3 (Donchian) + R5 onwards.
