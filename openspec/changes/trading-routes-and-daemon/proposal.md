## Why

Wave 3 shipped 13 archived slices: research-domain primitives (R1/R2/R3/R4/R5), trading primitives (T1/T2/T3), risk + approval channels (K1/P1), observability (O1) + scheduling (O2), dashboard skeleton (W1). **Each slice ships its own domain in isolation; no slice ties them together.** Today the bot can:

* Synthesise a research brief (R5) but not act on it.
* Generate a Donchian-ATR proposal (T3) but not route it through risk/approval/broker.
* Connect to IBKR (T2) but no service tells it which orders to place.
* Schedule routines (O2) but no routine kicks off the actual propose→execute cycle.

**Slice T4 is the keystone**: it wires the propose→risk→approve→execute pipeline that turns the bot into a working agent. Without T4, Wave 3 is a collection of well-tested abstractions with no end-to-end happy path.

## What Changes

- **`TradingService.propose(symbol, bars)`** — orchestrates `StrategyManager.evaluate_all` → emits `Proposal`s → persists `trade_proposals` rows → publishes `ProposalCreated` event for K1's risk engine to consume.
- **K1 risk-evaluation handler** — subscribes to `ProposalCreated`; computes `risk_evaluation` via existing engine; persists `risk_evaluations` row; emits `ProposalApprovedByRisk` or `ProposalRejectedByRisk` event.
- **P1 approval router handler** — subscribes to `ProposalApprovedByRisk`; emits approval requests to Telegram/Hermes via the existing channels; consumes operator decisions; persists `approval_decisions` row; emits `ProposalApprovedByOperator` or `ProposalRejected` event.
- **`TradingService.execute_on_approval(proposal_id)`** — subscribes to `ProposalApprovedByOperator`; constructs `NewOrder` with `client_order_id=uuid4()`; calls `IBKRAdapter.place_order`; on success persists `orders` row + emits `OrderPlaced` event; on `BrokerAuthError` / `BudgetExceededError` persists `orders` row with `state='rejected'` + emits `OrderRejected`.
- **Fill stream consumer** — `IBKRAdapter.reconcile_fills(since=last_seen)` driven on heartbeat tick; each `FillEvent` persists `fills` row + updates `orders.state` (`filled` or `partially_filled`) + emits `OrderFilled`.
- **Equity snapshot writer** — every fill triggers `IBKRAdapter.get_account_equity` + persists `equity_snapshots` row.
- **API routes (full impl, replaces T1 stubs)** — `GET /trades/proposals/{id}` + `GET /trades/orders/{id}` + `POST /trades/proposals/{id}/approve` (manual override path).
- **Daemon entrypoint** — `iguanatrader trading run --mode paper --tenant <name>` launches a long-running async worker that: (1) starts the IBKRAdapter heartbeat loop, (2) registers the bus subscriptions wiring all 6 handlers, (3) registers the O2 scheduler routines, (4) blocks on `asyncio.Event` for SIGTERM.
- **Out of scope**: backtesting (separate slice), multi-tenant queue isolation (v2 SaaS), per-strategy cost attribution beyond brief synthesis.

## Capabilities

- `trading`: adds `propose` + `execute_on_approval` orchestration + 6 bus subscribers + daemon entrypoint.

## Impact

- **R5/T2/T3/K1/P1/O2 are read-only consumed** — no edits to their archived surfaces.
- **New code in `apps/api/src/iguanatrader/contexts/trading/`**: `service.py` body fill (T1 left it stubbed), `daemon.py` (NEW), `handlers.py` (NEW — bus subscribers), `dtos/trading.py` route DTO additions.
- **Migration: none** — T1 already shipped the schema.
- **Tests**: integration test exercising full propose→execute happy path against in-memory bus + IBKRFake + FakeLLMClient + sqlite. Property test asserting no double-submission across 100 random retry sequences.

## Prerequisites

All Wave 3 slices archived (R1-R5 + T1-T3 + K1/P1 + O1/O2 + W1).

## Out of scope

- Real LLM client (deployment-foundation).
- Real Anthropic SDK (deployment-foundation).
- Frontend trade-detail page (a future W2 slice).
- Backtest harness (a future T5 slice).
- Multi-strategy aggregation beyond union (T3 default).

## Acceptance

- End-to-end integration test: synthesise brief → propose → risk-approve → operator-approve via fake P1 channel → IBKRFake placeOrder → fill arrives → orders.state=filled → equity_snapshots row written.
- `iguanatrader trading run` daemon boots cleanly + accepts SIGTERM cleanly.
- Idempotency: re-running `execute_on_approval(proposal_id)` for the same proposal is a no-op (returns existing order).
