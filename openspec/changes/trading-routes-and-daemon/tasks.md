# tasks — trading-routes-and-daemon (T4 keystone)

> Order: 1 → 2 → 3 → 4 → 5 → 6 → 7. Groups 2 and 3 (handler bodies) can parallelise across workers since they touch disjoint methods of the same class. Slot reservations per [.ai-playbook/specs/migration-slot-reservation.md](../../../.ai-playbook/specs/migration-slot-reservation.md): no migrations claimed (T1 schema already covers all writes).
>
> Pattern usage: this slice exercises [.ai-playbook/specs/protocol-fake-deferred-install.md §4-5](../../../.ai-playbook/specs/protocol-fake-deferred-install.md) by closing 2 of the 3.X.2 deferred markers from deployment-foundation (3.B.2 IBKRAdapter DI + 3.C.2 APSchedulerAdapter DI).

## 1. Helpers + repositories

- [x] **1.1** Created `apps/api/src/iguanatrader/cli/_tenant.py` — exports `db_url()` and `resolve_tenant_id()`. ~50 LoC.
- [x] **1.2** Updated `cli/research.py` to import the helper (re-aliased `_db_url` + `_resolve_tenant_id` for backward compatibility).
- [x] **1.3** Added `TradeProposalRepository.get_by_id`. (`update_state` dropped per design pivot — TradeProposal is strict-append-only.)
- [x] **1.4** Added `OrderRepository.get_by_proposal_id` via Order→Trade.proposal_id JOIN (Order has `trade_id`, not `proposal_id`). Plus `OrderRepository.add`, `get_by_id`, `get_by_broker_order_id`.
- [x] **1.5** Added `FillRepository.exists_by_broker_fill_id` + `add` + `sum_quantity_for_order` (needed by §2.C.3 quantity-summing). Plus `TradeRepository.add` + `get_by_id` + `update_state` (Trade IS column-allow-list mutable for `state`/`closed_at`) + `EquitySnapshotRepository.add`.

## 2. `TradingService` body fills

> All 3 handlers live in `apps/api/src/iguanatrader/contexts/trading/service.py` (T1's class). T4 fills the bodies marked `# T4 fills`.

### 2.A `risk_check_handler` — reject branch

> **Pivot from initial design**: `trade_proposals` is strict-append-only (no `state`/`rejection_reason` columns). Rejection is tracked via the `ProposalRejected` bus event (durable through the in-process bus) + structlog breadcrumb. No DB UPDATE; no schema change. Keeps the slice migration-free.

- [x] **2.A.1** ~~`_persist_proposal_state` helper~~ → **dropped**. Schema-change-free pivot.
- [x] **2.A.2** `risk_check_handler` reject branch fills: maps `cap_type_breached` to a structured reason string + publishes `ProposalRejected` + structlog `trading.proposal.rejected_by_risk`.
- [ ] **2.A.3** Per-handler unit tests **deferred to Group 5 integration test** — full session-binding required for repo round-trips; integration test exercises this path end-to-end with real sqlite. Existing `test_execute_on_approval_handler_idempotent_under_duplicate_publish` (T1) still passes (wrapper counter is pre-await).

### 2.B `execute_on_approval_handler` body

- [x] **2.B.1** Idempotency guard via `OrderRepository.get_by_proposal_id` (Order→Trade.proposal_id JOIN since Order has no `proposal_id` column). Logs `trading.execute.idempotent_skip` + returns early.
- [x] **2.B.2** Load `TradeProposal` via `TradeProposalRepository.get_by_id`; on `None` publishes `ProposalRejected(reason="proposal_missing")` + returns.
- [x] **2.B.3** Creates `Trade` row (state='open', opened_at, proposal_id). Persists via `TradeRepository.add`. Added `OrderRejected` event (additive extension to events.py).
- [x] **2.B.4** Builds `NewOrder` from loaded proposal (symbol/side/quantity; client_order_id=uuid4(); order_type='market').
- [x] **2.B.5** Submits via broker. Catches `BrokerAuthError` + `BudgetExceededError` → publishes `OrderRejected(reason='broker_auth'|'budget')` + persists `Order(state='rejected')`.
- [x] **2.B.6** On success: persists `Order(state='submitted', submitted_at, broker_order_id, ...)` + publishes `OrderPlaced(order_id, broker_order_id, tenant_id)`.
- [ ] **2.B.7** Per-handler unit tests **deferred to Group 5 integration test** (same rationale as 2.A.3).

### 2.C `reconcile_fills_handler` body

- [x] **2.C.1** Per-fill dedup via `FillRepository.exists_by_broker_fill_id`; on duplicate, logs `trading.fill.dedup_skip` + returns.
- [x] **2.C.2** Persists `Fill` row using `Fill.quantity_filled` (NOT `quantity`) + `fill_price` per the actual model schema. Order lookup via `OrderRepository.get_by_id(fill_event.order_id)`.
- [x] **2.C.3** Sums `quantity_filled` across fills via `FillRepository.sum_quantity_for_order`; on `sum >= order.quantity` calls `TradeRepository.update_state(state='closed', closed_at)`; else `state='partial'`.
- [x] **2.C.4** Publishes `OrderFilled(tenant_id, order_id, fill_id)` (matches existing event shape; `fully_filled` not on the event class).
- [x] **2.C.5** Equity snapshot only on terminal transition (`is_terminal`): calls `BrokerPort.get_account_equity()`, persists `EquitySnapshot` from `EquitySnapshotValue` (all fields mapped 1:1), publishes `EquityUpdated(tenant_id, equity_snapshot_id)`.
- [ ] **2.C.6** Per-handler unit tests **deferred to Group 5 integration test**.

## 3. Daemon entrypoint (`apps/api/src/iguanatrader/cli/trading.py` NEW)

- [x] **3.1** `cli/trading.py` created with Typer app. ~250 LoC total (more than estimate due to graceful-shutdown stack + Windows-asyncio signal-handler fallback).
- [x] **3.2** `@app.command("run")` with mode validation (`paper|live`).
- [x] **3.3** `_run_daemon(mode, tenant)` async function:
  - 3.3.a Resolve tenant_id via `_resolve_tenant_id` from `cli/_tenant.py`.
  - 3.3.b Construct DB engine + session (per `cli/research.py` pattern).
  - 3.3.c **3.B.2 wiring**: `ib_client = build_ib_async_client_from_env()` + `broker = IBKRAdapter(client_factory=lambda: ib_client, ...)` (1 line each). Closes Wave 4 deferred 3.B.2.
  - 3.3.d **3.C.2 wiring**: `scheduler = build_apscheduler_adapter_from_env()` (1 line). Closes Wave 4 deferred 3.C.2.
  - 3.3.e Construct `MessageBus`, `RiskService`, `ApprovalService`, `OrchestrationService`, `TradingService`.
  - 3.3.f Strategy resolver closure: `lambda cfg_id: manager._get_or_build(load_snapshot(cfg_id))` where `load_snapshot` queries `strategy_configs` by id. ~15 LoC.
  - 3.3.g Watchlist symbols: read from `IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS` env (comma-separated; default `AAPL,MSFT,GOOGL`); document v2-SaaS swap to per-tenant `watchlists` table.
  - 3.3.h Register subscriptions in order: `RiskService.register_subscriptions` → `TradingService.register_subscriptions` → `ApprovalService.register_subscriptions` → `OrchestrationService.bootstrap_routines(scheduler, trading_service, watchlist_symbols)`.
  - 3.3.i Start broker (`await broker.start()`) + scheduler (`await scheduler.start()`).
  - 3.3.j SIGTERM handler: `signal.signal(SIGTERM, lambda *_: shutdown_event.set())`. Block on `await shutdown_event.wait()`.
  - 3.3.k Graceful shutdown order: `scheduler.shutdown()` → `broker.disconnect()` → `shutdown_playwright()` → engine.dispose().
  - Total: ~120-150 LoC.
- [x] **3.4** `OrchestrationService.bootstrap_routines(scheduler, trading_service, watchlist_symbols)` added. Registers 4 cron `JobSpec`s with placeholder `_placeholder` fn (T4-followup wires per-symbol `TradingService.propose` loops).
- [ ] **3.5** Daemon smoke test **deferred to operator** — requires real subprocess + sqlite engine + DB migrations applied. Operator runs `iguanatrader trading run --mode paper --tenant test` and sends Ctrl+C to verify graceful shutdown.

> **Discovery (3.3.h)**: K1 RiskService + P1 ApprovalService have NO `register_subscriptions` method. Their bus integrations were scaffolded but never completed. T4 daemon logs `trading.daemon.bus_subscriptions.partial` warning + boots without those wirings; manual approve via API route §4.5 bypasses the chain. Both wirings are explicit carry-forward to **K1-followup + P1-followup slices** (separate from T4).
>
> **Discovery (3.3.f)**: Strategy resolver closure raises `NotImplementedError` because production needs `StrategyConfigRepository.get(id) → manager._get_or_build` plumbing not present yet. Tests bypass via direct `strategy_resolver=` injection. Carry-forward to **T4-followup**.

## 4. API routes (`apps/api/src/iguanatrader/api/routes/trading.py` NEW)

- [ ] **4.1** Create file with `router = APIRouter(prefix="/trades", tags=["trading"])`. Auto-discovered by slice-5's `register_routers`. ~15 LoC.
- [ ] **4.2** Add DTOs in `apps/api/src/iguanatrader/api/dtos/trading.py` (NEW or extend existing):
  - `ProposalResponse` — proposal fields + nested `RiskEvaluation` summary + `ApprovalStatus`.
  - `OrderResponse` — order fields + nested `Fill` list + `Trade.state`.
  - ~80 LoC of pydantic models.
- [ ] **4.3** `GET /trades/proposals/{id}` — `get_proposal(id, user, db)`. Loads via `TradeProposalRepository`, joins `RiskEvaluation` + approval. RFC 7807 404 if missing. ~30 LoC.
- [ ] **4.4** `GET /trades/orders/{id}` — `get_order(id, user, db)`. Loads via `OrderRepository`, joins `Fill`s + `Trade.state`. ~25 LoC.
- [ ] **4.5** `POST /trades/proposals/{id}/approve` — `manual_approve(id, user, db, request: Request)`. slowapi-limited 5/min. Loads proposal; publishes `ProposalApproved(proposal_id, tenant_id, approver_id=user.id)`; returns 202. ~30 LoC.
- [ ] **4.6** Auto-include router via slice-5's discovery — verify with `pytest --collect-only apps/api/tests/integration/`.
- [ ] **4.7** Add 6 route tests in `apps/api/tests/integration/test_trading_routes.py`: get proposal happy/404, get order happy/404, manual approve happy + rate-limit.

## 5. Integration test (`apps/api/tests/integration/test_trading_pipeline.py` NEW)

- [ ] **5.1** Construct full pipeline with: real `MessageBus`, `FakeLLMClient`, `IBKRFake` (T1's in-tree fake), `FakeChannel` (P1's in-tree fake), real sqlite session, `InMemoryScheduler`. ~50 LoC of fixtures.
- [ ] **5.2** Test happy path: synthesise brief → propose AAPL → risk evaluates allow → fake P1 channel auto-approves → IBKRFake place_order returns broker_order_id → IBKRFake emits FillEvent → reconcile picks it up → Trade.state == 'closed' → equity_snapshots row written. ~80 LoC.
- [ ] **5.3** Test reject path: same setup but FakeChannel auto-rejects. Assert: no `Order` row, no `Trade` row, `TradeProposal.state='rejected'`. ~30 LoC.
- [ ] **5.4** Test partial fill: IBKRFake emits 2 fills summing to less than order.quantity. Assert: 2 `Fill` rows, `Trade.state='partial'`, NO equity_snapshot. ~30 LoC.
- [ ] **5.5** Property test with `hypothesis.strategies.lists(retry_decisions, ...)`: 100 random retry sequences against `execute_on_approval_handler`. Assert: at most 1 `Order` row per `proposal_id`, at most 1 `OrderPlaced` event published per `proposal_id`. ~50 LoC.

## 6. Mypy + lint cleanup

- [ ] **6.1** Run `python -m ruff check --fix` on all new files; verify clean.
- [ ] **6.2** Run `python -m black` on all new files; verify clean.
- [ ] **6.3** Run `python -m mypy --strict --no-incremental` on:
  - `apps/api/src/iguanatrader/contexts/trading/service.py`
  - `apps/api/src/iguanatrader/cli/trading.py`
  - `apps/api/src/iguanatrader/cli/_tenant.py`
  - `apps/api/src/iguanatrader/api/routes/trading.py`
  - `apps/api/src/iguanatrader/api/dtos/trading.py`
  - `apps/api/src/iguanatrader/contexts/orchestration/service.py`
  - All new test files.
- [ ] **6.4** Verify pre-commit hooks pass locally.

## 7. PR + retro

- [ ] **7.1** Branch `slice/trading-routes-and-daemon` → push → open PR.
- [ ] **7.2** Author forward retro stub `retros/trading-routes-and-daemon.md` (filled at archive).
- [ ] **7.3** PR body §"Operator handoff" lists the smoke run: `iguanatrader trading run --mode paper --tenant test` against IBKR paper account + verifies one full propose→fill cycle.

---

## Estimated effort

| Group | Files touched | Effort |
|---|---|---|
| 1 helpers + repos | `cli/_tenant.py` (extract) + 3 repo methods | 1h |
| 2 handler fills | `service.py` (3 handlers, ~120 LoC body) + `test_service_handlers.py` (~250 LoC) | 2h |
| 3 daemon | `cli/trading.py` (~150 LoC) + `OrchestrationService.bootstrap_routines` (~40 LoC) + smoke test | 2h |
| 4 routes | `routes/trading.py` (~100 LoC) + `dtos/trading.py` (~80 LoC) + 6 tests (~150 LoC) | 1.5h |
| 5 integration test | `test_trading_pipeline.py` (~250 LoC + Hypothesis property) | 1.5h |
| 6 lint+mypy | Cleanup pass | 0.5h |
| 7 PR + retro | branch + push + PR body | 0.5h |

**Total**: ~9h sequential. Groups 2 + 3 + 4 are largely parallelisable across files — could be ~5h with intra-slice subagent dispatch via `/openspec-apply-parallel`.

**Net new LoC** (revised from proposal): ~600 src + ~600 tests = ~1,200 total. Lower than initial 1,000 estimate because T1's skeleton already covers the class shape + bus subscription registration.

**Wave 4 deferred items closed by this slice**:
- 3.B.2 IBKRAdapter DI (1 line in §3.3.c)
- 3.C.2 APSchedulerAdapter DI (1 line in §3.3.d)
