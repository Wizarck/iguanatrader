## Context

Slice T1 plants the **trading bounded context** that holds together the entire downstream Wave 3 + Wave 4 trading family:

- **Slice T2 `ibkr-adapter-resilient`** implements `BrokerPort` over `ib_async` + `HeartbeatMixin` — its only contract source is T1's `ports.py`.
- **Slice T3 `donchian-strategy-mvp`** implements `StrategyPort` over Donchian-channels + ATR sizing — its only contract source is T1's `ports.py`.
- **Slice T4 `trading-routes-and-daemon`** consolidates routes / SSE / CLI / frontend pages — every endpoint body it ships replaces a 501 stub T1 plants. DTOs are stable from T1.
- **Slice K1 `risk-engine-protections`** subscribes to `trading.proposal.created` events from T1's `events.py` and emits `trading.proposal.risk_evaluated` back. The MessageBus contract crosses bounded contexts (per slice 2 D1), so T1 owns the wire-format dataclasses; K1 only consumes/emits.
- **Slice P1 `approval-channels-multichannel`** subscribes to `trading.proposal.risk_evaluated` and emits `trading.proposal.approved` / `trading.proposal.rejected` back.
- **Slice O1 `observability-cost-meter`** subscribes to every `trading.*` event for cost tracking + structlog narration.

The challenge is **interface stability under parallel execution**. Wave 3 has T2 + T3 running in worktree-isolated parallel; if either could mutate `ports.py` after T1 lands, the other would race on the merge. Same logic for `events.py` (K1, P1, O1 all subscribe in parallel under Wave 2; the event names + payloads MUST be frozen by T1 close-out).

The migration story is the second half. `migrations/versions/` lands `0003_trading_tables.py` adjacent to R1's `0002_research_tables.py`; both are children of slice-3's `0001_initial_schema.py` + slice-4's `0002_users_role_enum.py`. Alembic linear chain requires `down_revision` to match the immediate parent. Since R1 ships `0002_research_tables.py` and slice 4 already shipped `0002_users_role_enum.py`, we have a numbering collision to resolve at integration time — the slice-4 migration is named `0002_users_role_enum.py` (extending the role enum), and R1's is `0002_research_tables.py`. Alembic uses the inline `revision = "..."` identifier (not the filename); the linear chain we adopt is **`0001_initial_schema → 0002_users_role_enum → 0002_research_tables → 0003_trading_tables`** with explicit `down_revision = '0002_research_tables'` declared in T1's migration. Filenames carry the slice's intent (zero-padded ordinal) but the revision string is what matters for `alembic upgrade head`. Documented in D5 below.

Slice 5's contract is consumed unchanged: `api/routes/__init__.py::register_routers` picks up `routes/trades.py`, `routes/portfolio.py`, `routes/strategies.py`, `routes/proposals.py` automatically — no `app.py` edit needed (anti-collision foundation working as designed). Every stub raises a new `NotImplementedFeatureError(IguanaError)` subclass; the slice-5 global handler renders RFC 7807 with `urn:iguanatrader:error:not-implemented` + 501 — every consumer (T4, frontend, integration tests) sees a uniform "feature not yet shipped" response shape until T4 lands.

## Goals / Non-Goals

**Goals:**

- Plant `BrokerPort` + `StrategyPort` Protocols in `contexts/trading/ports.py` with method signatures stable enough that T2 + T3 satisfy them via PEP 544 structural typing without back-edit pressure on T1.
- Land the migration `0003_trading_tables.py` covering `strategy_configs` / `trade_proposals` / `trades` / `orders` / `fills` / `equity_snapshots` per `docs/data-model.md §3.2` — including the cross-slice FK `trade_proposals.research_brief_id → research_briefs(id)` (R1 dependency).
- Declare the inter-context event contract in `events.py` with frozen names + payload shapes so K1 / P1 / O1 can subscribe in parallel.
- Plant the `service.py` orchestrator with the five-step sequence stubbed (`propose → risk_check → enqueue_approval → execute_on_approval → reconcile_fills`) so T4 has the wiring to extend.
- Plant DTOs (`api/dtos/trades.py`, `api/dtos/proposals.py`) so the OpenAPI typegen pipeline emits TypeScript counterparts on first push (slice-5 contract continuity).
- Plant route stubs returning 501 + RFC 7807 so the frontend (slice W1) can fetch the OpenAPI surface and resolve types without 404s on missing endpoints.
- Configure the slice-3 append-only listener for the new tables: `trade_proposals` / `fills` / `equity_snapshots` are pure append-only; `trades` / `orders` / `strategy_configs` opt into the column-level whitelist pattern.

**Non-Goals:**

- No IBKR adapter, no `ib_async` import anywhere — T2 owns it.
- No Donchian / SMA / strategy `manager.py` — T3 owns it.
- No live route bodies, no CLI subcommands, no frontend pages, no E2E happy-path test — T4 owns them.
- No risk engine, no caps math, no protections — K1 owns; T1 only emits `ProposalCreated`.
- No approval channel, no Telegram / Hermes / WhatsApp — P1 owns; T1 only emits `ProposalRiskEvaluated`.
- No structlog config / cost meter / OTEL — O1 owns; T1 emits events with NFR-O8-compliant names but doesn't own the sink.
- No backtest mode (removed 2026-04-28 per Gate A amendment); `mode` CHECK constraint = `IN ('paper','live')` only.
- No tenant-bootstrap CLI (slice T4 ships `bootstrap-tenant`).

## Decisions

### D1. `BrokerPort` + `StrategyPort` declared as PEP 544 `Protocol` subclasses of `shared.ports.Port`, NOT ABCs

**Decision**: `apps/api/src/iguanatrader/contexts/trading/ports.py` exposes:

```python
class BrokerPort(Port, Protocol):
    async def place_order(self, order: NewOrder) -> BrokerOrderId: ...
    async def cancel_order(self, broker_order_id: BrokerOrderId) -> None: ...
    async def reconcile_fills(self, since: datetime) -> AsyncIterator[FillEvent]: ...
    async def get_position(self, symbol: str) -> Position: ...
    async def get_account_equity(self) -> EquitySnapshot: ...

class StrategyPort(Port, Protocol):
    def name(self) -> str: ...
    def version(self) -> str: ...
    def evaluate(self, symbol: str, bars: BarHistory, config: StrategyConfig) -> Proposal | None: ...
```

T2's `IBKRAdapter` and T3's `DonchianATRStrategy` will satisfy these structurally; mypy --strict enforces conformance at type-check time. No `isinstance(adapter, BrokerPort)` runtime check is wired (the marker is `@runtime_checkable` from slice 2 but we don't lean on it).

**Alternatives considered**:

- **`abc.ABC` + `@abstractmethod`**: forces inheritance; an adapter author has to import `BrokerPort` from `contexts.trading.ports` to subclass — that's a cross-context dependency that ruff's `no-cross-context-deep-imports` rule (slice 2 acceptance) would flag. Protocol breaks the dependency.
- **Loose duck-typing without a Protocol**: defers all type-safety to runtime; mypy can't tell you that the IBKR adapter is missing `cancel_order` until T2's tests run.
- **`functools.singledispatch`-style registration**: registry-based, harder to enumerate at boot, doesn't compose with FastAPI dep injection.

**Rationale**: PEP 544 is the project's canonical pattern (slice 2 D8). The Protocol shape is documented contract; the adapter author writes a normal class; mypy verifies the match.

**Method-shape rationale**:

- `place_order` returns broker-side `BrokerOrderId` (str newtype) — caller (`service.py::execute_on_approval`) records this on the `orders.broker_order_id` column.
- `reconcile_fills(since)` is an `AsyncIterator[FillEvent]` — supports the slice-T2 reconciliation-on-reconnect contract (after a disconnect, the adapter pulls fills since the last known timestamp + emits each as a `FillEvent` to MessageBus).
- `evaluate` returns `Proposal | None` — `None` means "no signal at this bar"; not an error.
- `name()` + `version()` on `StrategyPort` enable the manager (slice T3) to dispatch by strategy_kind + version for hot-reload (FR4).

### D2. `service.py` orchestration sequence — `propose → risk_check → enqueue_approval → execute_on_approval → reconcile_fills` — wired via `MessageBus` events, NOT direct method calls

**Decision**: `TradingService` does NOT call `RiskService.evaluate()` or `ApprovalService.enqueue()` directly. Instead, it publishes domain events to the `MessageBus`:

1. `propose(symbol, strategy_id)` calls `StrategyPort.evaluate`, persists a `trade_proposals` row, publishes `ProposalCreated(proposal_id, ...)`.
2. K1's `RiskService` subscribes to `ProposalCreated`, runs the risk engine, publishes `ProposalRiskEvaluated(proposal_id, outcome, decision)`.
3. T1's `TradingService` subscribes to `ProposalRiskEvaluated`. If outcome is `allow` or `clip`, it publishes `ApprovalRequested(proposal_id, decision)`.
4. P1's `ApprovalService` subscribes to `ApprovalRequested`, dispatches to the user via Telegram/Hermes, awaits response, publishes `ProposalApproved(proposal_id)` or `ProposalRejected(proposal_id, reason)`.
5. T1's `TradingService` subscribes to `ProposalApproved`, calls `BrokerPort.place_order`, persists `orders` row, publishes `OrderPlaced(order_id, broker_order_id)`.
6. T1's `TradingService` subscribes to broker-side `FillEvent` (emitted by T2 adapter on `reconcile_fills` or live fill push), persists `fills` row + updates `trades.state`, publishes `OrderFilled(order_id, fill_id)`.

In slice T1 the bodies are stubbed — `propose` is the only method with a non-trivial body (it owns the proposal-creation half); the other handlers are registered subscribers with `# T4 fills` comments + structured logging.

**Alternatives considered**:

- **Direct method calls (`risk_service.evaluate(proposal)`)**: creates cross-context import edges that the ruff rule forbids. Couples risk to trading at compile time; impossible to test trading in isolation without a `RiskService` stub.
- **Sync-RPC style (FastAPI calls trading → trading calls risk → trading calls approval)**: blocks the request thread on approval channel latency (Telegram round-trip can be tens of seconds). The async-event pattern decouples request lifecycle from approval lifecycle.
- **Workflow engine (LangGraph-style state machine)**: heavyweight; slice O2 (`orchestration-scheduler-routines`) brings LangGraph for premarket/midday/postmarket; trading orchestration is the wrong place for it (each step is a single async call, not a multi-node workflow).

**Rationale**: events match the bounded-context decomposition (each context owns its slice of the lifecycle; communication is via published facts, not method calls). MessageBus FIFO-per-subscriber + opt-in idempotency (slice 2 D1) gives ordering guarantees + replay-safety for `ProposalApproved` (idempotency_key = proposal_id; if approval channel double-sends, only one OrderPlaced).

**Trade-off**: tracing the lifecycle of one proposal across logs requires correlating by `proposal_id` (or `correlation_id` per `trade_proposals.correlation_id` column). Slice O1's structlog config will handle this via `correlation_id` context-binding.

### D3. `events.py` declares 8 inter-context event types with frozen wire shapes — names follow `<context>.<entity>.<action>` per NFR-O8

**Decision**: `apps/api/src/iguanatrader/contexts/trading/events.py` exposes these dataclasses (subclasses of `iguanatrader.shared.messagebus.Event`):

| Event | Producer | Consumer(s) | Idempotency Key |
|---|---|---|---|
| `ProposalCreated` | T1 (`TradingService.propose`) | K1 (RiskService), O1 (cost meter narration) | `proposal_id` |
| `ProposalRiskEvaluated` | K1 | T1 (next step), O1 | `proposal_id` |
| `ApprovalRequested` | T1 | P1 (ApprovalService), O1 | `proposal_id` |
| `ProposalApproved` | P1 | T1 (`execute_on_approval`), O1 | `proposal_id` |
| `ProposalRejected` | P1 | T1, O1 | `proposal_id` |
| `OrderPlaced` | T1 | T2 reconciliation worker, O1 | `order_id` |
| `OrderFilled` | T1 (on fill event from T2) | T1 (`update_equity`), O1 | `fill_id` |
| `EquityUpdated` | T1 (`update_equity`) | UI-stream consumers (slice W1's SSE/equity), O1 | `equity_snapshot_id` |

Plus one additional event type owned by the kill-switch domain that crosses into trading but is published by K1 — declared in K1, NOT here:

- `KillSwitchTripped` (K1 publishes; T1 subscribes to halt all `propose` + `execute_on_approval` calls). T1's `events.py` does NOT redeclare this; it imports from `contexts.risk.events` (read-only consumption). Cross-context import is OK because events are the documented inter-context wire format (ruff rule excludes `events.py` paths from the cross-context import ban — slice-2 contract).

**Naming**: structlog event names + bus event class `__name__` lowercased to dotted form: `trading.proposal.created`, `trading.proposal.risk_evaluated`, `trading.approval.requested`, etc. Dispatched via the `event_name: ClassVar[str]` attribute on each dataclass (matches slice-2 `messagebus.Event` extension pattern).

**Alternatives considered**:

- **Strings ad-hoc per producer**: drift; consumers can't pattern-match. Rejected.
- **Enum-based event types**: closes the type system but adds churn when a new event type lands (every consumer must update their match). Dataclasses + `isinstance` checks via MessageBus's per-event-type subscription model already give the same exhaustiveness via mypy.
- **Pub/sub topic strings**: same as enum but stringly-typed. Worst of both worlds.

**Rationale**: dataclasses are the slice-2 idiom. Frozen names = no merge collisions when K1 + P1 + O1 add subscribers in parallel. The `event_name` attribute is structlog-friendly and matches the NFR-O8 `<context>.<entity>.<action>` convention.

### D4. `trade_proposals` is fully append-only via `__tablename_is_append_only__ = True`; `trades` + `orders` opt into column-level whitelist; `strategy_configs` is mutable with audit via `config_changes`

**Decision**: per `docs/data-model.md §3.2` notes:

- **Pure append-only** (listener rejects all UPDATE/DELETE): `trade_proposals`, `fills`, `equity_snapshots`. ORM declares `__tablename_is_append_only__ = True` on these models.
- **Column-level whitelist** (listener allows UPDATE only on enumerated columns): `trades` (state, closed_at), `orders` (state, broker_order_id, submitted_at, acknowledged_at, closed_at). The slice-3 listener supports this via `__append_only_mutable_columns__: ClassVar[frozenset[str]]` (already in the listener contract). Documented inline in each model class.
- **Mutable** (listener has no opinion): `strategy_configs` — but every UPDATE triggers a `config_changes` row insert via a SQLAlchemy event hook (slice O1 owns the `config_changes` table; T1 just declares the hook stub as `# wired in O1`).

**Alternatives considered**:

- **All-mutable** (no listener config): violates FR46 + NFR-SC2; rejected.
- **All-append-only including `trades` / `orders`**: would force a state-event-sourcing pattern (each state transition becomes a new row). Slice-2/data-model decision was that querying `WHERE state = 'open'` must be sub-millisecond; row-state-mutability is the explicit exception with column whitelist.

**Rationale**: data-model.md §3.2 line-for-line. Append-only enforcement is centralised in the slice-3 listener — slice T1 just declares the per-model class attributes and the listener does the rest.

### D5. Cross-slice FK `trade_proposals.research_brief_id → research_briefs(id)` requires explicit merge order R1 → T1 (Wave 2 sequencing constraint)

**Decision**: T1's migration `0003_trading_tables.py` declares:

```python
revision = "0003_trading_tables"
down_revision = "0002_research_tables"  # R1's revision string

# inside upgrade():
sa.Column("research_brief_id", sa.Uuid(), sa.ForeignKey("research_briefs.id", ondelete="RESTRICT"), nullable=True),
```

The FK is **nullable** because (per data-model.md note on `trade_proposals`) proposals generated before the research domain is operational don't reference a brief. Once R5 (`research-brief-synthesis`) lands and the synthesizer wires `research_brief_id` to the active brief at proposal time, the column gets populated; existing rows stay NULL.

**Merge order constraint**: R1 (`research-bitemporal-schema`) MUST be merged into `main` before T1. If T1 is merged first, the migration's FK target table doesn't exist and `alembic upgrade head` fails on a fresh DB. Both slices are Wave 2 and run in parallel, but T1's PR must be sequenced after R1's per the dependency graph in `docs/openspec-slice.md`.

CI gate: T1's `tests/integration/test_trading_migration.py` runs `alembic upgrade head` on a fresh SQLite DB; passes only if R1's migration is in the `versions/` directory (which it will be once R1 is merged). On the slice-T1 branch, R1's migration is pulled in via rebase before opening the PR.

**Alternatives considered**:

- **Drop the FK; just store `research_brief_id` as a UUID without referential integrity**: violates audit-trail invariant (FR74 + data-model §6 cross-context FK table); broken-reference rows would be undetectable. Rejected.
- **Use a deferred constraint that activates at session commit**: SQLite doesn't support deferred FKs; PostgreSQL does, but adding it complicates the cross-DB compat. The merge-order constraint is simpler and explicit.
- **Land both migrations in the same slice (combine R1 + T1)**: violates slicing principle (one bounded context per slice). Rejected.

**Rationale**: alembic linear chain + nullable FK is the lightest pattern. Merge order is a one-line documentation entry in this design doc + a CI gate in `test_trading_migration.py`.

### D6. Route stubs raise `NotImplementedFeatureError` → 501 RFC 7807 — pattern mirrors slice-5 D9 `BootstrapNotReadyError`

**Decision**: `apps/api/src/iguanatrader/shared/errors.py` gets one new subclass:

```python
class NotImplementedFeatureError(IguanaError):
    default_status = 501
    default_title = "Feature Not Implemented"
    type_uri = "urn:iguanatrader:error:not-implemented"
```

Every route in `api/routes/{trades,portfolio,strategies,proposals}.py` calls `raise NotImplementedFeatureError(detail=f"GET /trades will be wired in slice T4 (trading-routes-and-daemon).")`. The slice-5 global exception handler renders `application/problem+json` with the canonical urn-form type URI.

**Alternatives considered**:

- **Return `HTTPException(status_code=501)` directly**: bypasses the RFC 7807 contract; client gets FastAPI's native `{"detail": "..."}` format instead of `Problem`. Inconsistent with slice 5.
- **Raise existing `IguanaError` (e.g., `InternalError`)**: 500 ≠ 501; semantically wrong (it's not an internal error, it's a not-yet-shipped feature).
- **Skip the route stubs entirely; let 404 do the job**: but the OpenAPI schema then doesn't include the route shape, frontend (W1) can't bind types, T4 has no scaffold to fill.

**Rationale**: slice 5 D9 established the precedent (one new IguanaError subclass to rectify a status-code-canonicalisation gap). Same pattern here: one new subclass to express "intentional 501 stub". Documented inline in `shared/errors.py` as "added 2026-05-05 by slice trading-models-interfaces to express stub-only routes; to be cited by T4 when bodies replace stubs (no longer raised once T4 ships)."

### D7. Repository pattern: per-entity `BaseRepository` subclasses; tenant filtering automatic via slice-3 listener

**Decision**: `apps/api/src/iguanatrader/contexts/trading/repository.py` declares:

```python
class StrategyConfigRepository(BaseRepository[StrategyConfig]): ...
class TradeProposalRepository(BaseRepository[TradeProposal]): ...
class TradeRepository(BaseRepository[Trade]): ...
class OrderRepository(BaseRepository[Order]): ...
class FillRepository(BaseRepository[Fill]): ...
class EquitySnapshotRepository(BaseRepository[EquitySnapshot]): ...
```

Each subclass adds domain-specific query helpers as needed (e.g., `TradeRepository.list_open(symbol: str | None = None) -> list[Trade]`). Tenant filtering is automatic — the slice-3 `tenant_listener` injects `tenant_id == tenant_id_var.get()` on every SELECT against `__tenant_scoped__ = True` models, which is the default. Slice T1 plants the repositories empty-bodied except for the type binding; T4 adds the query helpers it needs.

`StrategyConfigRepository.upsert(symbol, strategy_kind, params, enabled)` is the one helper T1 plants concretely — required for FR2/FR3 (enable/disable + per-symbol config). It bumps `version` on every UPDATE and triggers the `config_changes` SQLAlchemy event hook (slice-O1 owned).

**Alternatives considered**:

- **Single `TradingRepository` god-object** with one method per query: violates SRP; harder to test in isolation; couples unrelated entities (strategy config UI doesn't care about fill history).
- **No repositories — use raw SQLAlchemy session in service.py**: works but every query duplicates the tenant filter (fragile), couples service to ORM details.
- **Generic CRUD helpers (Django-style managers)**: too magic; slice-2 `BaseRepository` is the documented pattern.

**Rationale**: BaseRepository[Model] is the slice-2 contract. Each entity gets its own subclass per the `contexts/<name>/repository.py` convention from `docs/project-structure.md`. Tenant filter is invisible to T1 — it's the listener's job; T1 inherits the guarantee.

## Risks / Trade-offs

- **[Risk] T2 + T3 + K1 + P1 add fields to events later, breaking T1's frozen wire shape** — if K1's risk engine needs a field on `ProposalRiskEvaluated` that T1 didn't anticipate, K1 would have to edit `events.py` after T1 closes. **Mitigation**: T1 ships every event with a `metadata: dict[str, Any] = field(default_factory=dict)` extension slot; K1 / P1 / O1 stuff additional context there without breaking the wire format. If a structural change is genuinely needed (new top-level field), it's a deliberate "events.py amendment" PR with cross-team review (mention in slice K1/P1's tasks if applicable).

- **[Risk] Migration 0003 fails to apply because R1 hasn't merged yet** — rebase pain or CI red. **Mitigation**: D5 documents the merge order; the slice-T1 PR description must include "blocked-on: R1 merged" as a prerequisite checkbox. CI gate: `test_trading_migration.py` runs `alembic upgrade head` on a fresh DB; if R1's migration is missing, the test fails loudly and the PR cannot merge.

- **[Risk] `trade_proposals.research_brief_id` is nullable indefinitely (R5 takes a long time to land), creating audit holes** — proposals without a linked brief defeat FR74. **Mitigation**: slice R5 (`research-brief-synthesis`) is in Wave 3 and lands before T4 (which is the first slice that actually generates live proposals). By T4 close, the synthesizer is wired and `research_brief_id` is non-NULL on every new row. Existing NULL rows are documented as "pre-research-domain" in `docs/gotchas.md`. Optional follow-up: a slice-O1 audit query that flags any post-R5 row with NULL brief.

- **[Risk] `BrokerPort.reconcile_fills(since)` returns an `AsyncIterator` but T2's IBKR API returns paginated batches synchronously** — adapter author has to hand-craft the async-iterator wrapper. **Mitigation**: slice T2's design will own the conversion; T1's contract is the right shape from the consumer's POV (TradingService doesn't want to manage pagination tokens). Documented in `BrokerPort.reconcile_fills` docstring.

- **[Risk] Route stubs returning 501 leak into production builds and confuse operators** — operator hits `/api/v1/trades` thinking it works, gets 501. **Mitigation**: each stub's Problem body's `detail` field names the slice that will land the implementation: `"GET /api/v1/trades will be wired in slice T4 (trading-routes-and-daemon)."` Operators reading the body get the roadmap inline. Frontend (W1) checks the type URI `urn:iguanatrader:error:not-implemented` and renders "coming soon" placeholder copy.

- **[Trade-off] Adding `NotImplementedFeatureError` grows the IguanaError hierarchy by one** — slice 2's design fixed the hierarchy, slice 5 already added `BootstrapNotReadyError`. T1's addition follows the same precedent ("rectify a stub-route gap, not a new error semantically"). Inline justification in `shared/errors.py`.

- **[Trade-off] `events.py` cross-context import edges** — `contexts.trading.events` imports `contexts.risk.events.KillSwitchTripped` for the trading service's halt-on-trip subscription. The ruff `no-cross-context-deep-imports` rule excludes `events.py` paths (events are the documented inter-context wire format per data-model §6). Documented inline.

## Migration Plan

This slice's deployment path:

1. **R1 merges first** (Wave 2 sequencing). Verify `migrations/versions/0002_research_tables.py` is on `main`.
2. **Rebase slice-T1 branch on `main` post-R1-merge**; `alembic upgrade head` on a fresh DB now succeeds (verifies the FK target exists).
3. **Merge slice T1 to main**. Migration applies forward; no destructive operations.
4. **Bot commits regenerated `packages/shared-types/src/index.ts`** (slice-5 typegen pipeline) with the new `Trade`, `Order`, `Fill`, `Proposal`, `EquitySnapshot`, `StrategyConfig` TypeScript interfaces. Slice W1 picks them up.
5. **Wave 3 unblocks**: T2 and T3 worktrees can now branch from `main` and start implementing against frozen `BrokerPort` / `StrategyPort` contracts. K1 / P1 / O1 (if not already in flight under Wave 2) can subscribe to `events.py`.

**Rollback** = revert PR. The migration includes a `downgrade()` that drops the 6 tables (no data exists in production yet — Wave 0/1/2 is pre-launch). No destructive operation against existing data.

## Open Questions

- **Q**: Does `service.py::propose` enforce a "one proposal per (symbol, strategy) within N seconds" debounce, or does the strategy port handle dedupe? **Tentative answer**: T1 plants the contract that strategies SHOULD return `None` when no new signal exists (no-op debounce); the service trusts the port. If strategies turn out to over-emit in practice, slice T3 adds debounce inside the strategy. T1 doesn't bake debounce into the service.

- **Q**: Should `Order.broker_order_id` be set at INSERT (eager) or post-broker-confirm (lazy)? **Tentative answer**: lazy — INSERT happens when `place_order` is called, but the broker's confirmation is async. The column is nullable post-INSERT and the listener whitelists it for UPDATE per D4. Documented inline in `models.py::Order`.

- **Q**: `equity_snapshots.snapshot_kind` enum includes `'tick'` per data-model.md §3.2 line 339, but data-model §7.2 says "drop tick, keep event + minute + daily". **Tentative answer**: follow the §7.2 update — final enum is `('event', 'minute', 'daily')`. T1's CHECK constraint uses the §7.2 set. Inconsistency is flagged in `docs/data-model.md` review (out of T1 scope to fix the doc, but the migration uses the correct enum).

- **Q**: Should `events.py` events include `tenant_id` in the payload, or rely on `tenant_id_var` context? **Tentative answer**: include `tenant_id` explicitly in every event. Subscribers running in a different async context (e.g., O1's structlog narrator running on a separate worker) cannot rely on the `contextvars` token having propagated. Explicit is safer. Documented in each event class docstring.
