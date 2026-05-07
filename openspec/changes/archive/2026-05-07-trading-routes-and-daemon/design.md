# Design — trading-routes-and-daemon (T4 keystone)

> **Purpose**: turn 13 archived Wave-3 slices into a working agent. T1 planted the skeleton (`TradingService` class + 6 handler stubs); T4 fills the bodies, wires the daemon entrypoint, registers the bus subscriptions, and ships the integration test that exercises the whole pipeline end-to-end.
>
> **Scope reality check**: T1 ALREADY built the `TradingService` shape (services file at [`contexts/trading/service.py`](../../../apps/api/src/iguanatrader/contexts/trading/service.py), 386 LoC). The skeleton's `# T4 fills` markers point exactly at the body fills this slice owns. **T4 is more wiring than authoring** — much of the LoC budget goes to handler bodies + the daemon + the integration test.

## 1. Architecture overview

The propose→execute pipeline is event-driven over the in-process [`MessageBus`](../../../apps/api/src/iguanatrader/shared/messagebus.py). Every step publishes one event class; subscribers consume + emit the next. No step calls another service's method directly.

```
┌────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│   Scheduler (O2 APSchedulerAdapter)                                          │
│   ─ premarket / midday / postmarket / weekly_review cron jobs                │
│                                  │                                           │
│                                  ▼                                           │
│   TradingService.propose(symbol, bars, config)        T1-shipped, T4 reuses  │
│     ─ StrategyManager.evaluate (T3)                                          │
│     ─ persist trade_proposals row                                            │
│     ─ publish ProposalCreated  ──────┐                                       │
│                                       │                                       │
│   ┌────────────── MessageBus ────────┴──────────────────────────────┐        │
│   │                                                                  │        │
│   │  ProposalCreated                                                 │        │
│   │   └─▶ RiskService.evaluate_proposal (K1, archived)               │        │
│   │        ─ persist risk_evaluations row                            │        │
│   │        ─ publish ProposalRiskEvaluated ──┐                       │        │
│   │                                          │                       │        │
│   │  ProposalRiskEvaluated                  │                       │        │
│   │   └─▶ TradingService.risk_check_handler  ◀─ T4 fills body        │        │
│   │        ─ on outcome=allow|clip → publish ApprovalRequested        │        │
│   │        ─ on outcome=reject     → persist no-trade audit          │        │
│   │                                                                  │        │
│   │  ApprovalRequested                                               │        │
│   │   └─▶ ApprovalService (P1, archived)                             │        │
│   │        ─ deliver_request via ChannelPort (Telegram / Hermes)      │        │
│   │        ─ on operator-approve → publish ProposalApproved           │        │
│   │        ─ on operator-reject → publish ProposalRejected            │        │
│   │                                                                  │        │
│   │  ProposalApproved                                                │        │
│   │   └─▶ TradingService.execute_on_approval_handler  ◀─ T4 fills    │        │
│   │        ─ idempotency check by proposal_id (orders table)         │        │
│   │        ─ create Trade row (state='open')                          │        │
│   │        ─ build NewOrder + IBKRAdapter.place_order                 │        │
│   │        ─ persist orders row + publish OrderPlaced                 │        │
│   │                                                                  │        │
│   │  Heartbeat tick (every 30s, T2 HeartbeatMixin)                   │        │
│   │   └─▶ TradingService.reconcile_fills_handler  ◀─ T4 fills        │        │
│   │        ─ IBKRAdapter.reconcile_fills(since=last_seen)             │        │
│   │        ─ persist fills row + update Trade.state                   │        │
│   │        ─ on terminal state → IBKRAdapter.get_account_equity       │        │
│   │        ─ persist equity_snapshots row + publish OrderFilled       │        │
│   └──────────────────────────────────────────────────────────────────┘        │
│                                                                              │
└────────────────────────────────────────────────────────────────────────────┘

Daemon entrypoint: `iguanatrader trading run --mode paper --tenant <name>`
     ─ Construct SecretEnv → IbAsyncIBClient → IBKRAdapter (3.B.2 wiring)
     ─ Construct APSchedulerAdapter (3.C.2 wiring)
     ─ Construct MessageBus + register all subscriptions
     ─ Start scheduler + heartbeat + signal handler
     ─ Block on asyncio.Event for SIGTERM, then graceful drain
```

## 2. Per-component specifications

### 2.1 `TradingService` body fills

The class shape from T1 is unchanged. T4 fills 3 handler bodies + 1 helper. **No new methods** are added to the public surface — the existing skeleton already declares them.

#### 2.1.1 `risk_check_handler(event: ProposalRiskEvaluated) -> None`

T1 ships the `allow|clip` branch (publishes `ApprovalRequested`). T4 adds:
- On `event.outcome == "reject"`: persist a no-trade audit row in `trade_proposals` (set `state='rejected_by_risk'` + `rejection_reason=event.reason`); publish `ProposalRejected` so the bus dispatches to P1's audit-only path; emit structlog `trading.proposal.rejected_by_risk`.
- The audit path is non-trivial: T4 adds a `_persist_proposal_state(proposal_id, state, reason)` private helper because `execute_on_approval_handler` will need the same state-mutation in its own no-trade paths.

#### 2.1.2 `execute_on_approval_handler(event: ProposalApproved) -> None`

T1 ships the skeleton call sequence + a stub `NewOrder`. T4 fills:

1. **Idempotency guard** (FIRST step): query `orders` table by `proposal_id`; if a row exists (from a previous execute attempt that survived bus dedup) return early + log breadcrumb. Return type stays `None` — re-emission of `OrderPlaced` for an already-placed order is the bus's job, not the handler's.
2. **Load `TradeProposal` by id** via the `TradeProposalRepository` (introduce in T4 if absent). Defensive: if the row is gone (e.g. wiped between approval and execute), publish `ProposalRejected` with `reason="proposal_missing"` + return.
3. **Create `Trade` row** with `state='open'`, `opened_at=utc_now()`, `proposal_id=event.proposal_id`. The `Trade` table already exists from T1.
4. **Construct `NewOrder`** by copying fields from the loaded `TradeProposal`: symbol, side, quantity, order_type (always 'market' in MVP), trade_id (just-created), tenant_id, client_order_id=uuid4().
5. **Submit via broker**: `await self._broker.place_order(new_order)`. Catch `BrokerAuthError` → publish `OrderRejected(reason='broker_auth')` + persist `orders` row with `state='rejected'`. Catch `BudgetExceededError` (O1's signal) → publish `OrderRejected(reason='budget')` + same persistence. Other exceptions propagate (the bus's exception barrier handles them).
6. **Persist `Order` row** with `broker_order_id`, `state='submitted'`, `placed_at=utc_now()`.
7. **Publish `OrderPlaced` event** with `proposal_id`, `order_id`, `broker_order_id`, `tenant_id`.

#### 2.1.3 `reconcile_fills_handler(since: datetime) -> None`

T1 ships the iteration shape (`async for _fill in self._broker.reconcile_fills(since)`). T4 fills the per-fill body:

1. **Persist `Fill` row** with idempotency by `broker_fill_id` (if a row already exists for the same broker_fill_id, skip — this matches IBKR's "exec_id is broker-stable" guarantee).
2. **Mutate `Trade.state`**: query the `Order.trade_id` for this fill; sum filled-quantity across `fills` rows; if `sum == order.quantity`, set `Trade.state='closed'` + `closed_at=utc_now()`; else set `Trade.state='partial'`.
3. **Publish `OrderFilled` event** with `trade_id`, `order_id`, `fill_id`, `fully_filled: bool`.
4. **Equity snapshot**: ONLY when `Trade.state` transitions to terminal (`closed` or `cancelled`). Call `await self._broker.get_account_equity()`; persist `equity_snapshots` row with `equity_usd`, `cash_usd`, `recorded_at=utc_now()`. This is T4-NEW (the existing repository has the schema; the persistence call is new).

The handler's tick cadence is the existing T2 `HeartbeatMixin.heartbeat_loop` — T4 does NOT introduce a new timer. Each heartbeat tick already calls `reconcile_fills_handler(since=last_seen)`; T1 wired the trigger.

### 2.2 Daemon entrypoint (`apps/api/src/iguanatrader/cli/trading.py` NEW)

Per the existing CLI pattern (`cli/research.py`) — a Typer subcommand under the auto-discovered CLI app.

```python
@app.command("run")
def run(
    mode: str = typer.Option(..., "--mode", help="paper | live"),
    tenant: str = typer.Option(..., "--tenant", help="Tenant slug"),
) -> None:
    """Run the iguanatrader trading daemon (long-running)."""
    asyncio.run(_run_daemon(mode=mode, tenant=tenant))
```

The `_run_daemon` async function:

1. **Validate mode**: `mode in {"paper", "live"}`; reject otherwise.
2. **Resolve tenant_id** via the existing `_resolve_tenant_id` helper from `cli/research.py` (extract to `cli/_tenant.py` to avoid copy).
3. **Construct DB engine + session** per the `cli/research.py` pattern.
4. **DI wiring (this is 3.B.2 + 3.C.2 from Wave 4)**:
   ```python
   from iguanatrader.contexts.trading.brokers.ib_async_client import build_ib_async_client_from_env
   from iguanatrader.contexts.orchestration.apscheduler_adapter import build_apscheduler_adapter_from_env

   ib_client = build_ib_async_client_from_env()
   broker = IBKRAdapter(client_factory=lambda: ib_client, ...)  # 3.B.2 ← single line
   scheduler = build_apscheduler_adapter_from_env()              # 3.C.2 ← single line
   ```
5. **Construct services**: `TradingService(bus, broker, strategy_resolver)`, `RiskService(...)`, `ApprovalService(...)`, `OrchestrationService(repo, scheduler=scheduler)`.
6. **Register subscriptions**: each service exposes `register_subscriptions(bus)`; daemon calls each in startup order:
   - `RiskService.register_subscriptions(bus)` — subscribes to `ProposalCreated` → `ProposalRiskEvaluated`
   - `TradingService.register_subscriptions(bus)` — subscribes to `ProposalRiskEvaluated`, `ProposalApproved`, `ProposalRejected`
   - `ApprovalService.register_subscriptions(bus)` — subscribes to `ApprovalRequested` → `ProposalApproved`/`ProposalRejected`
   - `OrchestrationService.bootstrap_routines(scheduler, trading_service)` — registers cron triggers with the APSchedulerAdapter calling `TradingService.propose` for each watchlist symbol on the schedule.
7. **Start broker connect + scheduler**: `await broker.start()` (heartbeat loop) + `await scheduler.start()`.
8. **SIGTERM handler**: `signal.signal(SIGTERM, lambda *_: shutdown_event.set())`. Block on `await shutdown_event.wait()`.
9. **Graceful shutdown** (in this exact order — order matters):
   - `await scheduler.shutdown()` — stops new routine triggers
   - `await broker.disconnect()` — drains heartbeat + closes TWS connection
   - `await shutdown_playwright()` — closes Tier-2 chromium browser if launched
   - Close DB engine

### 2.3 API routes (NEW: `apps/api/src/iguanatrader/api/routes/trading.py`)

Three endpoints, all delegate to `TradingService` + repositories:

| Method + Path | Handler | Returns |
|---|---|---|
| `GET /trades/proposals/{id}` | `get_proposal(id)` | `ProposalResponse` (full proposal + risk evaluation if any + approval status) |
| `GET /trades/orders/{id}` | `get_order(id)` | `OrderResponse` (order + fills + Trade state) |
| `POST /trades/proposals/{id}/approve` | `manual_approve(id, user)` | 202 + publishes `ProposalApproved`; rate-limited 5/min |

**Manual approve** is the operator-override path (the channel-based approve goes through P1). It bypasses the Telegram/Hermes channel and emits `ProposalApproved` directly. Subject to the same idempotency guard as channel-driven approval (the bus dedups; `execute_on_approval_handler` re-checks via `orders` table).

## 3. Anti-patterns explicitly rejected

- **Direct service-to-service method calls** — every cross-context coupling MUST go through the bus. `TradingService` does NOT import `RiskService`; `RiskService` does NOT import `ApprovalService`. The wiring lives only in the daemon entrypoint.
- **Background timer threads** — every async loop is the asyncio event loop. No `threading.Timer`, no `asyncio.create_task` orphans (every task is awaited or attached to a tracked set).
- **Polling for fills** — the heartbeat tick is the trigger; there's no separate poll loop. Fill arrival is event-driven from IBKR's API push; reconcile is the catch-up path.
- **Multi-tenant queue isolation** — out of scope for MVP; one tenant per daemon process. Multi-tenant SaaS daemons land in v2.
- **Strategy hot-reload at runtime** — out of scope. Restarting the daemon picks up the new strategy version. T3's `StrategyManager` supports hot-reload; we choose not to wire it in T4 to keep the daemon simple.

## 4. Migration / rollback discipline

- **No new migrations** — T1 already shipped `trade_proposals`, `orders`, `fills`, `trades`, `risk_evaluations`, `equity_snapshots`. T4 only INSERTs/UPDATEs into the existing tables.
- **Rollback path**: if T4 introduces a regression (e.g. infinite execute-loop), kill the daemon (SIGTERM); operator's `kubectl rollout undo` reverts to the previous image. The append-only `equity_snapshots` table makes the financial state recoverable from the broker's source-of-truth.
- **Per-route deploy** is impossible — the daemon owns the bus subscriptions. Either the whole image moves or nothing does. The Helm chart's StatefulSet `replicas: 1` enforces this.

## 5. Acceptance gates

Beyond proposal.md §"Acceptance":

- **Integration test** at [`apps/api/tests/integration/test_trading_pipeline.py`](../../../apps/api/tests/integration/test_trading_pipeline.py) (NEW): synthesise brief → propose → risk-approve → operator-approve via fake P1 channel → IBKRFake place_order → fill arrives → `orders.state=filled` → `trades.state=closed` → `equity_snapshots` row written. Uses real in-memory bus + FakeLLMClient + FakeChannel + IBKRFake + sqlite.
- **Property test** with Hypothesis: 100 random retry sequences against `execute_on_approval_handler` — no double broker submissions, no double `OrderPlaced` events, no double `Trade` rows.
- **Daemon smoke**: `iguanatrader trading run --mode paper --tenant test` boots cleanly + accepts SIGTERM cleanly within 5s. Exit code 0.
- **Mypy --strict** clean across all new files.
- **License-boundary CI** unaffected (no new deps).

## 6. Interaction with deployment-foundation

T4 is the slice that **closes Wave 4 deferred items 3.B.2 + 3.C.2**:

- 3.B.2 IBKRAdapter DI: `broker = IBKRAdapter(client_factory=lambda: build_ib_async_client_from_env(), ...)` — single line in §2.2 step 4.
- 3.C.2 APSchedulerAdapter DI: `scheduler = build_apscheduler_adapter_from_env()` — single line in §2.2 step 4.

Both are documented + factory-ready since deployment-foundation merge (`f1ec433`).

Tests STILL inject the fakes (`IBKRFake`, `InMemoryScheduler`) — env-gated production wiring is the daemon's concern only.

## 7. Open questions

- **Strategy resolver implementation**: T1's `StrategyResolver = Callable[[UUID], StrategyPort]` is a callable type alias with no canonical implementation. T4 needs to plug in T3's `StrategyManager.get_strategy(strategy_config_id)` — does this method exist or does T4 need to add it? **Resolution**: check T3's archive; if absent, add a thin `_resolve_strategy(strategy_config_id)` method to `StrategyManager` and document the addition as a T4 side-effect.
- **Watchlist enumeration for routine wiring**: O2's scheduler routines fire at cron boundaries; what symbols do they iterate? The proposal.md says "for each watchlist symbol on the schedule" — does T4 need to query a `watchlists` table? **Resolution**: T4 introduces a `WatchlistRepository.list_active(tenant_id)` if absent; uses an env-driven default (`IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS=AAPL,MSFT,...`) for first-cut.
