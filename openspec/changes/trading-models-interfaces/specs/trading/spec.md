## ADDED Requirements

### Requirement: `BrokerPort` Protocol declares the broker-side interface that the IBKR adapter (slice T2) implements

The system SHALL expose `iguanatrader.contexts.trading.ports.BrokerPort` as a PEP 544 `Protocol` subclass of `iguanatrader.shared.ports.Port` with the following async methods: `place_order(order: NewOrder) -> BrokerOrderId`, `cancel_order(broker_order_id: BrokerOrderId) -> None`, `reconcile_fills(since: datetime) -> AsyncIterator[FillEvent]`, `get_position(symbol: str) -> Position`, `get_account_equity() -> EquitySnapshot`. Concrete adapters (e.g., `IBKRAdapter` in slice T2) SHALL satisfy the contract structurally; `mypy --strict` SHALL flag any missing or mistyped method. No runtime `isinstance` check is required; the marker base is `@runtime_checkable` only for defensive use at module boundaries.

#### Scenario: A class with matching signatures satisfies BrokerPort under mypy --strict

- **WHEN** a developer writes `class IBKRAdapter:` in `apps/api/src/iguanatrader/contexts/trading/brokers/ibkr_adapter.py` with the five methods having signatures matching `BrokerPort`
- **AND** the developer writes `def execute(broker: BrokerPort, order: NewOrder) -> ...:` somewhere in `service.py` and calls `execute(IBKRAdapter(), order)`
- **THEN** `mypy --strict` accepts the call without error (structural typing)
- **AND** the slice-T1 unit test `test_ports_protocol_conformance.py` declares a stub `class _StubBroker:` with the matching shape and asserts `isinstance(_StubBroker(), BrokerPort)` is `True` (runtime-checkable verification)

#### Scenario: A class missing a method fails mypy --strict against BrokerPort

- **WHEN** a developer writes a class missing `cancel_order`
- **AND** assigns it to a `BrokerPort`-typed variable
- **THEN** `mypy --strict` reports `error: Incompatible types in assignment ... missing 'cancel_order'`
- **AND** the unit test `test_ports_protocol_conformance.py` includes a `# type: ignore[assignment]` xfail case asserting the same shape mismatch is detected

### Requirement: `StrategyPort` Protocol declares the strategy-side interface that Donchian (slice T3) implements

The system SHALL expose `iguanatrader.contexts.trading.ports.StrategyPort` as a PEP 544 `Protocol` subclass of `iguanatrader.shared.ports.Port` with the methods `name() -> str`, `version() -> str`, `evaluate(symbol: str, bars: BarHistory, config: StrategyConfig) -> Proposal | None`. The `evaluate` method's docstring SHALL explicitly forbid lookahead — strategies see only `bars[t < now]`; the no-lookahead invariant is enforced via property tests in slice T3 (`tests/property/test_strategy_no_lookahead.py`).

#### Scenario: Returning None from evaluate is the canonical "no signal" path

- **WHEN** `StrategyPort.evaluate(symbol="SPY", bars=..., config=...)` returns `None`
- **THEN** `TradingService.propose` records no `trade_proposals` row and emits no `ProposalCreated` event
- **AND** the structlog event `trading.strategy.no_signal` is emitted with `symbol`, `strategy_kind`, `strategy_version` for observability

#### Scenario: A strategy reports its name + version for hot-reload tracking

- **WHEN** the manager (slice T3) loads two versions of `donchian_atr` (one running, one newly configured)
- **THEN** `StrategyPort.name()` returns `"donchian_atr"` for both
- **AND** `StrategyPort.version()` returns the version string (matching the `strategy_configs.version` column) so the manager can replace the running instance atomically per FR4

### Requirement: `TradingService` orchestrates the propose → fills sequence via published MessageBus events

The system SHALL provide `iguanatrader.contexts.trading.service.TradingService` whose public methods stub the five-step sequence: `propose(symbol, strategy_id) -> Proposal`, `risk_check_handler(event: ProposalCreated) -> None` (subscriber callback), `enqueue_approval_handler(event: ProposalRiskEvaluated) -> None`, `execute_on_approval_handler(event: ProposalApproved) -> None`, `reconcile_fills_handler(event: FillEvent) -> None`. Inter-step communication SHALL use the `MessageBus` (slice 2) — no direct method call to `RiskService` / `ApprovalService` / `BrokerPort` from within a handler except via published events. Slice T1 plants the wiring; bodies remain skeletal (the `propose` half is functional; downstream handlers log + comment "wired in T4").

#### Scenario: propose() emits ProposalCreated event

- **WHEN** `TradingService.propose(symbol="SPY", strategy_id=...)` is called
- **AND** the strategy returns a `Proposal` (non-None)
- **THEN** a `trade_proposals` row is INSERTed with the strategy's reasoning + research_brief_id
- **AND** a `ProposalCreated` event is published to the MessageBus with `idempotency_key=str(proposal_id)`
- **AND** the structlog event `trading.proposal.created` is emitted with `proposal_id`, `symbol`, `strategy_kind`, `tenant_id`, `correlation_id`

#### Scenario: ProposalApproved triggers BrokerPort.place_order

- **WHEN** P1's ApprovalService publishes `ProposalApproved(proposal_id=...)` to the MessageBus
- **AND** `TradingService.execute_on_approval_handler` is the registered subscriber
- **THEN** the handler calls `BrokerPort.place_order(NewOrder.from_proposal(...))`
- **AND** an `orders` row is INSERTed (broker_order_id NULL until broker confirm)
- **AND** an `OrderPlaced(order_id, broker_order_id)` event is published

#### Scenario: KillSwitchTripped halts new proposals

- **WHEN** K1's `KillSwitchTripped` event is published to the MessageBus
- **AND** `TradingService.halt_handler` is the registered subscriber
- **THEN** subsequent calls to `TradingService.propose` raise `KillSwitchActiveError` (501-stub-equivalent until T4)
- **AND** the structlog event `trading.service.halted` is emitted with the trip reason from the event payload

### Requirement: `events.py` declares the inter-context event contract with frozen wire shapes

The system SHALL expose `iguanatrader.contexts.trading.events` as the canonical wire-format module for the trading bounded context's outbound + inbound MessageBus events. The module SHALL define dataclass subclasses of `iguanatrader.shared.messagebus.Event` for: `ProposalCreated`, `ProposalRiskEvaluated`, `ApprovalRequested`, `ProposalApproved`, `ProposalRejected`, `OrderPlaced`, `OrderFilled`, `EquityUpdated`. Every event class SHALL carry: a `event_name: ClassVar[str]` matching the `<context>.<entity>.<action>` structlog convention, `tenant_id: UUID` (explicit, NOT relying on contextvars per design D3 trade-off), the entity's primary key as `idempotency_key`-derivable, and a `metadata: dict[str, Any]` extension slot for downstream subscribers (K1, P1, O1) to enrich without breaking the wire format.

#### Scenario: Event class includes the canonical event_name attribute

- **WHEN** the test suite introspects `ProposalCreated.event_name`
- **THEN** the value is the literal string `"trading.proposal.created"`
- **AND** the same convention holds for the other 7 event classes (`trading.proposal.risk_evaluated`, `trading.approval.requested`, etc.)

#### Scenario: Subscriber registers with idempotency for proposal-keyed events

- **WHEN** `bus.subscribe(ProposalApproved, handler, idempotent=True)` is called by `TradingService`
- **AND** the same `ProposalApproved(proposal_id=X)` is published twice (e.g., P1 retried delivery)
- **THEN** the second publish is silently suppressed at the subscriber boundary (slice 2 D1 guarantee)
- **AND** `BrokerPort.place_order` is invoked exactly once

### Requirement: Trading route modules return RFC 7807 501 stubs until slice T4 lands the bodies

The system SHALL provide route modules `apps/api/src/iguanatrader/api/routes/{trades,portfolio,strategies,proposals}.py` each exporting a top-level `router: APIRouter` (so the slice-5 dynamic discovery picks them up) with the canonical endpoint paths declared but every handler raising `NotImplementedFeatureError` whose `detail` field names the slice that will land the implementation (`"... will be wired in slice T4 (trading-routes-and-daemon)."`). The slice-5 global exception handler SHALL render every such raise as `application/problem+json` HTTP 501 with `type=urn:iguanatrader:error:not-implemented`.

#### Scenario: GET /api/v1/trades returns 501 with canonical Problem body

- **WHEN** an authenticated client issues `GET /api/v1/trades`
- **THEN** the response is `501 Not Implemented` with `Content-Type: application/problem+json`
- **AND** the body is `{"type": "urn:iguanatrader:error:not-implemented", "title": "Feature Not Implemented", "status": 501, "detail": "GET /api/v1/trades will be wired in slice T4 (trading-routes-and-daemon)."}`
- **AND** the OpenAPI schema for the endpoint declares the response model so slice-5's typegen pipeline emits the matching TypeScript interface for the eventual response shape (the route declares `response_model=TradeOut` even though the body never returns a real `TradeOut` in T1)

#### Scenario: NotImplementedFeatureError inherits from IguanaError + slice-5 handler renders Problem

- **WHEN** the test suite raises `NotImplementedFeatureError(detail="...")` from a stub route
- **THEN** the slice-5 `_render_problem` handler is invoked (per FastAPI MRO) and produces the RFC 7807 body
- **AND** the structlog event `trading.routes.stub_invoked` is emitted with `path`, `method`, `tenant_id` for observability tracking of "how often does the frontend hit a stub" until T4 lands

### Requirement: Migration `0003_trading_tables.py` lands the trading-context tables with append-only listener config and cross-slice FK to `research_briefs`

The system SHALL ship `apps/api/src/iguanatrader/migrations/versions/0003_trading_tables.py` with `revision="0003_trading_tables"` and `down_revision="0002_research_tables"` (R1's migration). The `upgrade()` SHALL create six tables — `strategy_configs`, `trade_proposals`, `trades`, `orders`, `fills`, `equity_snapshots` — matching `docs/data-model.md §3.2` line-for-line: column types, NOT NULL constraints, CHECK constraints (`side IN ('buy','sell')`, `mode IN ('paper','live')`, etc.), indexes (per data-model index list), and the cross-slice FK `trade_proposals.research_brief_id → research_briefs(id) ON DELETE RESTRICT` (nullable). The `downgrade()` SHALL drop the six tables in reverse-FK order. The migration SHALL pass `alembic upgrade head` and `alembic downgrade -1` on a fresh SQLite DB only when R1's migration is also present in the `versions/` directory.

#### Scenario: Fresh DB upgrade succeeds when R1 migration is present

- **WHEN** the test fixture creates a fresh SQLite DB and runs `alembic upgrade head` against a `versions/` containing `0001_initial_schema.py`, `0002_users_role_enum.py`, `0002_research_tables.py`, `0003_trading_tables.py`
- **THEN** all four migrations apply in order
- **AND** introspection (`PRAGMA table_info('trade_proposals')`) shows the `research_brief_id` column exists with FK to `research_briefs(id)`
- **AND** the test passes

#### Scenario: Fresh DB upgrade fails loudly when R1 migration is missing

- **WHEN** the test fixture creates a fresh DB with `versions/` containing slice-T1's migration but NOT R1's `0002_research_tables.py`
- **THEN** `alembic upgrade head` raises (no `0002_research_tables` revision found)
- **AND** the CI gate fails the slice-T1 PR until R1 is rebased in
- **AND** the test asserts the specific revision-not-found error to make the merge-order constraint visible

#### Scenario: Append-only listener rejects UPDATE on trade_proposals

- **WHEN** a session attempts to UPDATE a `trade_proposals` row's `reasoning` field
- **THEN** the slice-3 append-only listener raises `AppendOnlyViolationError` before the SQL hits the driver
- **AND** the integration test `test_trading_migration.py::test_proposals_append_only` asserts the raise

#### Scenario: Column-level whitelist allows UPDATE only on trade.state and trade.closed_at

- **WHEN** a session UPDATEs `trades.state` from `"open"` to `"closed_filled"` and sets `trades.closed_at`
- **THEN** the listener allows the UPDATE (both columns are in the whitelist `__append_only_mutable_columns__ = frozenset({"state", "closed_at"})`)
- **AND** an UPDATE attempt against `trades.symbol` raises `AppendOnlyViolationError`

### Requirement: DTOs in `api/dtos/{trades,proposals}.py` mirror the trading entities and feed the OpenAPI typegen pipeline

The system SHALL expose Pydantic v2 models in `apps/api/src/iguanatrader/api/dtos/trades.py` (`TradeOut`, `OrderOut`, `FillOut`, `EquitySnapshotOut`, `StrategyConfigOut`, `StrategyConfigIn`) and `apps/api/src/iguanatrader/api/dtos/proposals.py` (`ProposalIn`, `ProposalOut`, paginated wrappers `TradeListOut`, `ProposalListOut`). Models SHALL set `model_config = ConfigDict(from_attributes=True)` so they construct cleanly from ORM instances. Field types SHALL use `Decimal` for money columns (slice 2 `Money` interop) and `UUID` for IDs. Route stubs SHALL declare these as `response_model=...` so the OpenAPI schema includes them and the slice-5 typegen pipeline emits the TypeScript counterparts on first push.

#### Scenario: ProposalOut roundtrips from ORM instance

- **WHEN** a unit test calls `ProposalOut.model_validate(proposal_orm_instance)` on an ORM `TradeProposal` row
- **THEN** the resulting Pydantic model carries `id`, `symbol`, `side`, `quantity`, `entry_price_indicative`, `stop_price`, `confidence_score`, `reasoning`, `research_brief_id`, `mode`, `correlation_id`, `created_at`
- **AND** the JSON schema contains the matching field names and types

#### Scenario: TypeScript regeneration picks up trade DTOs after first CI push

- **WHEN** the slice-T1 PR is pushed and the slice-5 `openapi-types.yml` workflow fires
- **THEN** `packages/shared-types/src/index.ts` is regenerated and contains exported interfaces `Trade`, `Order`, `Fill`, `EquitySnapshot`, `StrategyConfig`, `Proposal`, `ProposalIn`, paginated wrappers
- **AND** the workflow-bot commit lands on the slice-T1 branch with message `chore(types): regenerate shared-types from /openapi.json`

### Requirement: Repositories follow the per-entity `BaseRepository[Model]` pattern with automatic tenant filtering

The system SHALL provide `iguanatrader.contexts.trading.repository` exposing `StrategyConfigRepository(BaseRepository[StrategyConfig])`, `TradeProposalRepository(BaseRepository[TradeProposal])`, `TradeRepository(BaseRepository[Trade])`, `OrderRepository(BaseRepository[Order])`, `FillRepository(BaseRepository[Fill])`, `EquitySnapshotRepository(BaseRepository[EquitySnapshot])`. Tenant filtering on every SELECT SHALL be automatic via the slice-3 `tenant_listener` (no per-query manual `WHERE tenant_id=...`). Slice T1 SHALL plant `StrategyConfigRepository.upsert(symbol, strategy_kind, params, enabled)` concretely (FR2/FR3 surface area); other repositories SHALL ship empty bodies (T4 adds query helpers).

#### Scenario: TradeRepository.get(id) automatically filters by tenant_id_var

- **WHEN** `tenant_id_var` is set to tenant A's UUID via the slice-4 `get_current_user` dep
- **AND** a test attempts `TradeRepository(session).get(trade_id_belonging_to_tenant_B)`
- **THEN** the result is `None` (the slice-3 listener appended `tenant_id == tenant_A`)
- **AND** no exception is raised — the cross-tenant access is silently filtered, matching slice-3 contract

#### Scenario: StrategyConfigRepository.upsert bumps version + triggers config_changes event hook

- **WHEN** `StrategyConfigRepository(session).upsert(symbol="SPY", strategy_kind="donchian_atr", params={"lookback": 20, "atr_mult": 2.0}, enabled=True)` is called against an existing row with `version=3`
- **THEN** the row's `params` and `enabled` columns are UPDATEd
- **AND** `version` is incremented to `4`
- **AND** the SQLAlchemy event hook fires emitting `trading.config.changed` (slice O1 wires the `config_changes` row insert; T1 only declares the hook stub + structlog event)
