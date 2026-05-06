## Why

Slice 5 (`api-foundation-rfc7807`) just landed the dynamic-discovery + RFC 7807 foundation that Wave 2 slices were waiting on. The trading bounded context is the heart of iguanatrader — every concrete adapter (T2 IBKR, T3 Donchian) and every consolidated route family (T4 trades/portfolio/strategies) downstream depends on a stable contract for **what a Proposal is, what a Broker does, what a Strategy does, and how the propose→fills sequence flows**. Today that contract does not exist: there are no trading models, no `BrokerPort` / `StrategyPort` Protocols for Wave 3 adapters to satisfy, no migration for `strategy_configs` / `trade_proposals` / `trades` / `orders` / `fills` / `equity_snapshots`, and no event-bus contract to plug `risk` (K1) / `approval` (P1) / `observability` (O1) into. Without this slice, T2 + T3 cannot run in parallel — they would race on `contexts/trading/ports.py` definition. T4 cannot draft routes without DTOs. K1 cannot subscribe to `trading.proposal.created` events without an emitter. Now is the right time because Wave 2 has just opened (R1, T1, K1, P1, O1, W1 in flight) and T1 is the only Wave-2 slice the entire trading family (T2, T3, T4) blocks on.

## What Changes

- **New bounded context `contexts/trading/`** — six modules planted as the public-API surface of the trading domain: `__init__.py`, `models.py` (ORM models), `ports.py` (`BrokerPort` + `StrategyPort` Protocols), `service.py` (orchestrator skeleton), `repository.py` (per-entity repositories on `BaseRepository`), `events.py` (inter-context event types). Adapters are NOT planted (T2 IBKR + T3 Donchian own those).
- **Migration `0003_trading_tables.py`** — Alembic migration for the 6 trading-context tables: `strategy_configs` (mutable; FR1-FR5), `trade_proposals` (append-only; FR11; carries `research_brief_id` FK to `research_briefs`), `trades` (state-mutable lifecycle row; FR46), `orders` (state-mutable; FR14, FR15), `fills` (pure append-only), `equity_snapshots` (append-only). Schema follows `docs/data-model.md §3.2` line-for-line; naming-convention-compliant constraints; CHECK constraints for enums (side, mode, state, snapshot_kind).
- **Append-only listener config** — `models.py` declares `__tablename_is_append_only__ = True` for `trade_proposals`, `fills`, `equity_snapshots`. `trades` and `orders` opt into the column-level whitelist pattern (only `state` + closed/filled timestamps mutable; documented in slice-3 `append_only_listener.py` contract).
- **`BrokerPort` Protocol** — `ports.py` declares `BrokerPort(Port, Protocol)` with the methods T2 will implement: `place_order(order: Order) -> BrokerOrderId`, `cancel_order(broker_order_id: BrokerOrderId) -> None`, `reconcile_fills(since: datetime) -> AsyncIterator[FillEvent]`, `get_position(symbol: str) -> Position`, `get_account_equity() -> EquitySnapshot`. PEP 544 structural typing per shared.ports D8.
- **`StrategyPort` Protocol** — `ports.py` declares `StrategyPort(Port, Protocol)` with the methods T3 will implement: `evaluate(symbol: str, bars: BarHistory, config: StrategyConfig) -> Proposal | None`, `name() -> str`, `version() -> str`. No-lookahead invariant documented in the docstring (T3 enforces in property tests).
- **`service.py` orchestrator skeleton** — TradingService class wires `MessageBus` + `BrokerPort` + `StrategyPort` + repositories. The five-step sequence is method-stubbed: `propose(symbol, strategy_id) -> Proposal`, `risk_check(proposal) -> RiskDecision` (delegates via event to risk context — K1 owns the engine), `enqueue_approval(proposal, decision) -> ApprovalRequestId` (via event to approval context — P1), `execute_on_approval(proposal_id) -> Order` (called when approval event arrives), `reconcile_fills() -> None` (broker event handler). Concrete bodies stay minimal — T4 fills them when the daemon lands.
- **`events.py` inter-context contract** — declares the event dataclasses that cross context boundaries: `ProposalCreated`, `ProposalRiskEvaluated`, `ProposalApproved`, `ProposalRejected`, `OrderPlaced`, `OrderFilled`, `EquityUpdated`, `KillSwitchTripped`. Event names follow the `<context>.<entity>.<action>` structlog convention (NFR-O8). Each event carries `idempotency_key` (slice-2 `MessageBus` opt-in) where the cross-context handler benefits from it.
- **DTOs `api/dtos/trades.py` + `api/dtos/proposals.py`** — Pydantic v2 models for the request/response shapes T4 will use: `TradeOut`, `ProposalIn`, `ProposalOut`, `OrderOut`, `FillOut`, `EquitySnapshotOut`, paginated list wrappers. No `routes/<x>.py` consumes these yet; T4 wires them to live endpoints. Slice T1 plants them so the OpenAPI typegen pipeline (slice-5 contract) emits the TypeScript counterparts on first CI push.
- **Route stubs returning 501** — `api/routes/trades.py`, `api/routes/portfolio.py`, `api/routes/strategies.py`, `api/routes/proposals.py` declare `router: APIRouter` and the canonical endpoint shapes (so `pkgutil.iter_modules` picks them up + the OpenAPI surface stabilises) but every handler raises `NotImplementedError` → mapped via slice-5 fallback handler to RFC 7807 `urn:iguanatrader:error:not-implemented` with HTTP 501. T4 replaces the bodies; route paths + DTOs are stable from T1 onwards.
- **Repository pattern** — `repository.py` exposes `StrategyConfigRepository`, `TradeProposalRepository`, `TradeRepository`, `OrderRepository`, `FillRepository`, `EquitySnapshotRepository`, all inheriting `BaseRepository[Model]` from slice 2. Tenant filtering is automatic via the slice-3 listener.
- **No adapters, no real strategies, no daemon, no backtest** — every concrete plug-in lives in its dedicated slice (T2 / T3 / T4). Slice T1 is interface-only.

## Capabilities

### New Capabilities

- `trading`: bounded-context contract for the trading domain — entities, ports, service skeleton, events, DTOs, route stubs, migration. The interface that T2 (IBKR adapter), T3 (Donchian strategy), T4 (routes + daemon), K1 (risk integration via events), P1 (approval integration via events) all depend on. Slice T1 plants the contract; slices downstream plug into it.

### Modified Capabilities

(none — `api-foundation` from slice 5 is consumed unchanged: route stubs use the dynamic-discovery pattern, errors raise `IguanaError` subclasses, DTOs feed the OpenAPI typegen pipeline.)

## Impact

- **Affected code (slice-T1-owned, write-allowed)**:
  - `apps/api/src/iguanatrader/contexts/trading/{__init__,models,ports,service,repository,events}.py` (NEW) — bounded context skeleton.
  - `apps/api/src/iguanatrader/migrations/versions/0003_trading_tables.py` (NEW) — 6 tables + constraints + indexes per `docs/data-model.md §3.2`.
  - `apps/api/src/iguanatrader/api/dtos/trades.py` (NEW) — Pydantic v2 trade/order/fill/equity DTOs.
  - `apps/api/src/iguanatrader/api/dtos/proposals.py` (NEW) — Pydantic v2 proposal DTOs.
  - `apps/api/src/iguanatrader/api/routes/trades.py` (NEW) — 501 stubs; T4 fills.
  - `apps/api/src/iguanatrader/api/routes/portfolio.py` (NEW) — 501 stubs.
  - `apps/api/src/iguanatrader/api/routes/strategies.py` (NEW) — 501 stubs.
  - `apps/api/src/iguanatrader/api/routes/proposals.py` (NEW) — 501 stubs.
  - `apps/api/src/iguanatrader/shared/errors.py` (MOD) — add `NotImplementedFeatureError(IguanaError)` with `default_status=501`, `type_uri="urn:iguanatrader:error:not-implemented"`. Re-export from `shared/__init__.py`. (Pattern mirrors slice-5 D9 `BootstrapNotReadyError` introduction.)
  - `apps/api/tests/unit/contexts/trading/{test_ports_protocol_conformance,test_service_orchestration,test_events_emission,test_repository_filters_tenant}.py` (NEW) — unit tests.
  - `apps/api/tests/integration/test_trading_route_stubs.py` (NEW) — assert 501 + RFC 7807 body shape on every stub endpoint.
  - `apps/api/tests/integration/test_trading_migration.py` (NEW) — Alembic upgrade/downgrade smoke + schema introspection assertions.
- **Affected code (read-only consumed from slice 2/3/4/5)**:
  - `iguanatrader.shared.{ports.Port, messagebus.{Event,MessageBus}, types.Money, kernel.BaseRepository, errors.IguanaError, time.utc_now, contextvars.tenant_id_var}` — slice-2 contracts consumed unchanged.
  - `iguanatrader.persistence.base.Base` (NEW model parent) and the slice-3 tenant + append-only listeners (active automatically for new models).
  - `iguanatrader.api.routes.__init__::register_routers` + `iguanatrader.api.errors.register_error_handlers` (slice-5 dynamic discovery + global RFC 7807 handler) — every new route module is auto-registered.
- **Affected APIs**: four NEW route prefixes appear in `/openapi.json` — `/api/v1/trades`, `/api/v1/portfolio`, `/api/v1/strategies`, `/api/v1/proposals` — every endpoint returns 501 + Problem until T4 lands. The TypeScript typegen pipeline emits the new DTOs to `packages/shared-types/src/index.ts` on first push.
- **Affected dependencies**: none new. Pydantic v2 + SQLAlchemy 2.0 + Alembic + FastAPI + Typer all already in slices 1-5.
- **Prerequisites**:
  - **slice 5 `api-foundation-rfc7807`** (Wave 1) — provides dynamic route discovery + RFC 7807 handler + `Problem` DTO.
  - **slice R1 `research-bitemporal-schema`** (Wave 2, parallel) — provides the `research_briefs` table that `trade_proposals.research_brief_id` references via FK. **Merge order constraint**: R1 MUST land before T1 since the migration cannot be applied in isolation; alembic `down_revision = '0002_research_tables'` (R1) NOT `'0002_users_role_enum'` (slice 4). Documented in design.md D5. CI gate: `alembic upgrade head` on a fresh DB must succeed only when both R1's migration and T1's are present in the migrations dir.
- **Capability coverage** (per `docs/openspec-slice.md` row T1 + `docs/prd.md`):
  - **FR1** (list strategies) → schema (`strategy_configs`) + repository + DTO (`StrategyOut`) + route stub.
  - **FR2** (enable/disable per symbol) → `strategy_configs.enabled` column + uniqueness `(tenant_id, strategy_kind, symbol)`.
  - **FR3** (per-symbol params via yaml/runtime) → `strategy_configs.params` JSON column.
  - **FR4** (hot-reload without restart) → `strategy_configs.version` column + service contract that strategies read fresh config on each `evaluate` call.
  - **FR5** (parameter override via approval channel) → DTO + service stub (`override_strategy_param`); P1 wires the channel command → event → service in its slice.
  - **FR11** (proposals carry structured reasoning) → `trade_proposals.reasoning` JSON column + `ProposalOut.reasoning` DTO field + `BrokerPort` / `StrategyPort` shapes.
  - **FR14** (broker submission via abstract interface) → `BrokerPort` Protocol; T2 implements.
  - **FR46** (append-only persistence of trades/orders/fills/positions/equity) → migration + listener config.
- **Out of scope** (per `docs/openspec-slice.md` row T1):
  - IBKR adapter (slice T2 owns `contexts/trading/brokers/ibkr_adapter.py`).
  - Donchian / SMA strategies (slice T3 owns `contexts/trading/strategies/*`).
  - Live route bodies + CLI subcommands + frontend pages + E2E tests (slice T4).
  - Risk engine logic (slice K1 — T1 only emits `ProposalCreated`; K1 subscribes and emits `ProposalRiskEvaluated` back).
  - Approval channel logic (slice P1 — T1 only emits `ProposalRiskEvaluated`; P1 subscribes and emits `ProposalApproved` / `ProposalRejected` back).
  - Cost meter / structlog config (slice O1 — T1 emits structlog events with NFR-O8-compliant names; O1 owns the sink + dashboard).
  - Backtest mode (removed 2026-04-28 per Gate A amendment; `mode CHECK IN ('paper','live')` enforced in migration).
