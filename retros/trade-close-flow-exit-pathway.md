# Retrospective: trade-close-flow-exit-pathway

Bundle of three sequential PRs that closed the trade lifecycle end-to-end:

- **PR [#170](https://github.com/Wizarck/iguanatrader/pull/170) — `ibkr-execution-algos-entry`** (merged 2026-05-15, squash `084d9aa`) — Market / Adaptive / TWAP on entry orders. +216 lines / 7 files.
- **PR [#171](https://github.com/Wizarck/iguanatrader/pull/171) — `trade-state-machine-redesign`** (merged 2026-05-15, squash `c1b28a0`) — collapse `closed_filled|closed_force_exit|closed_canceled` → `closed`, add `closing`, migration 0017. +161 / 8 files.
- **PR [#172](https://github.com/Wizarck/iguanatrader/pull/172) — `trade-close-flow-exit-pathway`** (merged 2026-05-15, squash `3cc3d8f`) — `POST /trades/{id}/close` + `CloseTradeRequested` event + `TradingService.close_trade_handler` + `_compute_realised_pnl` + `_reconcile_one_fill` entry-vs-exit branching. +798 / 6 files.

Combined: 1,175 lines across 21 files. No archive directory created — these were sequential PRs without an openspec proposal/tasks scaffold (3-PR plan agreed in-line with Arturo).

## What worked

- **Three small PRs over one mega-PR** — splitting on natural boundaries (broker algos / state-machine / orchestration) let each PR land independently with reviewable scope. Mega-PR estimate would've been ~1.2k lines + a migration + a new endpoint + new event — too much for one review window.
- **State machine semantic correction** — pre-slice, `closed` meant "entry filled" (no exit even contemplated). PR #171 reframed it to "trade terminated" with `closing` covering the in-flight exit. The dimensionality (`stop|target|manual|expiry`) moves to `exit_reason` instead of being smeared across state values. This is the model the protections (stoploss-guard, daily-loss-cap, cooldown, max-drawdown) actually needed — risk queries were silently broken because `state != 'open'` matched too aggressively.
- **Idempotency via bus dedup, not via service guards** — `CloseTradeRequested.idempotency_key = str(trade_id)`. The message bus rejects duplicate close requests for the same trade; the service-level `TradeNotClosableError` is defence-in-depth, not the primary gate. No new locking primitives.
- **Append-only whitelist extension stayed minimal** — added `{"state", "closed_at", "exit_reason", "realised_pnl"}` to the mutable column set on `Trade`. Everything else stays write-once. The audit-table-as-history pattern (from trailing-stops) wasn't repeated here — these fields are end-state, not drift.
- **Entry vs exit branching reads off `order.side != trade.side`** — no new "exit_order" boolean column, no event-type fanout. The order's side already encodes intent (long trade close = sell order). One-line check in `_reconcile_one_fill` decides whether to update equity or terminate the trade.
- **Compute realised P&L from fill history, not from cached fields** — `_compute_realised_pnl` aggregates entry + exit fills from `FillRepository.list_for_trade` at terminal-fill time. Avoids the "double-write derived value" trap where the cached number can drift from the fills it derives from.

## What didn't

- **Migration 0017 double-prefix on constraint name** — project naming convention `ck_%(table_name)s_%(constraint_name)s` re-prefixed `ck_trades_state_allowed` into `ck_trades_ck_trades_state_allowed`. Fixed with `op.f("ck_trades_state_allowed")` to opt out of the convention's prefix-rewrite. Add to playbook — every new check-constraint migration will hit this.
- **Migration 0015 test bombed by 0017** — `test_migration_0015` used `command.downgrade(alembic_config, "-1")` which now reverts 0017, not 0015. Renamed + pinned to explicit revision `0014_user_recovery_channels`. Pattern: any `command.downgrade(..., "-1")` is brittle the moment another migration lands. Always pin to the explicit prior revision.
- **`_reconcile_one_fill` missing `commission_currency` + `filled_at`** — latent NOT NULL violation in the Fill ORM build. Tests didn't catch it because no prior fill-reconcile test had hit the terminal-fill path with non-zero commission. Bundled the fix in PR #172.
- **Cross-tenant equity guard tripped by `_FakeBroker.get_account_equity`** — the broker fake returned `tenant_id=uuid4()` per call; the tenant-listener rejected it. Fixed by passing the test's `tenant_id` to the fake's constructor. Pattern: broker fakes that emit tenant-keyed objects need explicit tenant injection — `uuid4()` defaults are a hidden cross-tenant bomb.
- **FK seeding in tests required N separate commits** — `StrategyConfig → TradeProposal → Trade → Order → Fill`. SQLite enforces FKs via `PRAGMA foreign_keys=ON` from the engine factory; flushing isn't enough. Same pattern blocks 4 tests in `test_append_only_listener_trading.py` (pre-existing, out of scope). Worth promoting to playbook: **every integration test that builds a Fill needs commits between each FK level**.
- **mypy `BrokerOrderId` NewType in test broker** — returned bare `str`, mypy --strict rejected. Trivial fix (`return BrokerOrderId(f"FAKE-{n:04d}")`) but the CI failure cost a round-trip. Pre-commit doesn't run mypy --strict; CI does.

## Carry-forward

- **Live broker validation pending IBKR paper approval** — paper account `DUR071858` / username `okqtbz074` filed but awaiting IBKR ops ("if received by 4 PM Eastern Time will be processed by next business day"). Once approved, smoke-test entry algos + close flow via IB Gateway 7497. Live creds also encrypted in `.secrets/live.env.enc` for the eventual prod cut.
- **Equity-snapshot daemon** — drawdown protection still reads 0 in production. Independent of this slice but it's now the single remaining blocker on max-drawdown firing in production.
- **`test_append_only_listener_trading.py` — 4 pre-existing FK failures** — same pattern as PR #169's fix. Not blocking this slice but worth a sweep.
- **CI pytest still `--collect-only`** — third consecutive slice this week shipped with at least one latent failure CI couldn't catch (commission_currency NULL, mypy NewType, etc). The collect-only cost is no longer hypothetical. Promote to top of the queue.

## Pattern usage

- **State value vs state dimension** — when a state value (`closed_force_exit`) encodes a reason, refactor reason out to its own column (`exit_reason`). The state machine then has fewer terminal values and the protections that query state get simpler. 1st explicit codification.
- **Idempotency via bus dedup on entity PK** — `idempotency_key = str(trade_id)` rejects duplicate close requests at the bus level. Defence-in-depth at the service is then a `TradeNotClosableError` raising on `state != "open"`, not a lock. 3rd use (proposal_id, order_id, trade_id).
- **Side-difference as exit-detection** — `order.side != trade.side` reliably identifies exit orders without adding a column or branching on event type. Works because trades are single-side by definition. Promote if a second use lands.
- **Migration constraint-naming opt-out** — `op.f("ck_<table>_<constraint>")` bypasses the project's naming-convention double-prefix when the constraint name is already canonical. Promote to playbook §alembic-naming-conventions.
- **Explicit prior revision in downgrade tests** — never `command.downgrade(cfg, "-1")`. Always pin to the named revision the test expects to land on. Promote to playbook §alembic-test-discipline.
