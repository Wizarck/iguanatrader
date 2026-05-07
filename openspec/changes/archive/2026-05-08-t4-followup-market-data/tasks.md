# tasks — t4-followup-market-data

> Order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11. Some groups are parallelisable in principle, but applying serially keeps mypy green at every checkpoint.
>
> **Migration slot**: `0012` reserved per [migration-slot-reservation.md](../../../.ai-playbook/specs/migration-slot-reservation.md). Latest existing: `0011_orchestration_tables`. Tables: `market_data_bars` (mutable, UPSERT), `market_data_sync_audit` (append-only).
>
> **Pattern usage**: third canonical instance of "skeleton-then-fill" + fresh canonical of "Protocol+InTreeFake+DeferredProductionInstall" (Port + 3 adapters all shipped together, NOT deferred).

## 1. Models + migration (foundation)

- [ ] **1.1** Add `MarketDataBar` SQLAlchemy model to `apps/api/src/iguanatrader/persistence/models.py`. Columns per design §2.6. NO `__append_only_mutable_columns__` (mutable, UPSERT-friendly). UniqueConstraint `(tenant_id, symbol, timeframe, ts)` named `market_data_bars_unique`. Index `market_data_bars_lookup` on `(tenant_id, symbol, timeframe, ts)`. ~30 LoC.
- [ ] **1.2** Add `MarketDataSyncAudit` model in same file. Columns per design §2.6. `__append_only_mutable_columns__ = ()` to opt into the slice-3 listener (UPDATE/DELETE → AppendOnlyViolation). Index `market_data_sync_audit_recent` on `(tenant_id, invoked_at)`. ~25 LoC. Use `sa.JSON` for `symbols` field on sqlite (the dialect-conditional ARRAY/JSON pattern from existing migrations — copy from `0007_observability_tables.py` if it has the same shape).
- [ ] **1.3** Author migration `apps/api/src/iguanatrader/migrations/versions/0012_market_data_tables.py`. `down_revision = "0011_orchestration_tables"`. `upgrade()` creates both tables with constraints/indexes; `downgrade()` drops them in reverse order. ~80 LoC. Verify the dialect-conditional ARRAY/JSON for `symbols` column matches existing migration patterns.
- [ ] **1.4** Run `make db-upgrade` locally (sqlite) to confirm migration applies. Then `make db-downgrade REV=-1` to confirm rollback. Run integration test `test_alembic_roundtrip.py` if it exists (it auto-discovers new revisions).

## 2. Port + 3 adapters

- [ ] **2.1** Add `MarketDataPort` Protocol to `apps/api/src/iguanatrader/contexts/trading/ports.py`. Plus `MarketDataNotAvailableError` + `MarketDataPacingViolationError` + `MarketDataRateLimitedError` to a new colocated `apps/api/src/iguanatrader/contexts/trading/market_data/__init__.py` or under existing `errors.py`. ~50 LoC total (Protocol + 3 errors).
- [ ] **2.2** Create package directory `apps/api/src/iguanatrader/contexts/trading/market_data/` with `__init__.py`. Author `in_memory.py` with `InMemoryMarketDataAdapter` per design §2.2. ~40 LoC.
- [ ] **2.3** Author `db.py` with `DBMarketDataAdapter` per design §2.3. Reads `session_var` + `tenant_id_var` lazily. ~50 LoC.
- [ ] **2.4** Author `ibkr_ingestor.py` with `IbAsyncMarketDataIngestor` per design §2.4. Includes `_fetch` (calls `ib_client.qualify_contract` + `reqHistoricalDataAsync`) + `_upsert` (SQLAlchemy `Insert.on_conflict_do_update` against `market_data_bars`). Includes `IngestResult` dataclass. ~120 LoC.

## 3. IngestionService + audit repo

- [ ] **3.1** Author `apps/api/src/iguanatrader/contexts/trading/market_data/repository.py` with `MarketDataSyncAuditRepository(BaseRepository)`. Methods: `count_invocations_since(since: datetime) -> int`, `write_audit_row(**kwargs) -> MarketDataSyncAudit`. ~50 LoC.
- [ ] **3.2** Author `apps/api/src/iguanatrader/contexts/trading/market_data/service.py` with `MarketDataIngestionService` per design §2.5. Includes the rate-limit check (audit row count in last hour vs env-var `IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR=10`), audit-row write on every branch, exception propagation. ~110 LoC.

## 4. Strategy config repository methods

- [ ] **4.1** Add `get_by_id(strategy_config_id: UUID) -> StrategyConfig | None` to `StrategyConfigRepository` in `apps/api/src/iguanatrader/contexts/trading/repository.py`. ~10 LoC.
- [ ] **4.2** Add `list_enabled_for_tenant_and_symbol(symbol: str) -> list[StrategyConfig]`. ~10 LoC. Both rely on slice-3 `tenant_listener` for tenant scoping.

## 5. Strategy resolver async signature change (touches T4 archive surface)

- [ ] **5.1** Update the `StrategyResolver` type alias in `apps/api/src/iguanatrader/contexts/trading/service.py` from `Callable[[UUID], StrategyPort]` to `Callable[[UUID], Awaitable[StrategyPort]]`. Add `await` at the callsite in `TradingService.propose` (line ~193: `strategy = await self._strategy_resolver(strategy_config_id)`). ~3 LoC.
- [ ] **5.2** Audit existing tests for the resolver-injection pattern. Tests that pass `lambda id: mapping[id]` need to become `async def _resolve(id): return mapping[id]`. Likely 3-5 test files. Adapt with a 1-line wrapper helper colocated in a `conftest.py` if needed.
- [ ] **5.3** Fill `_make_strategy_resolver` in `apps/api/src/iguanatrader/cli/trading.py` per design §2.10. The closure now async; signature changes from `() -> StrategyResolver` to `(*, session_factory) -> StrategyResolver`. Replace `NotImplementedError` with the real lookup body. ~25 LoC.

## 6. `bootstrap_routines` per-symbol propose loops + 5th routine

- [ ] **6.1** Update `OrchestrationService.bootstrap_routines` signature to accept `market_data_port: MarketDataPort`, `strategy_config_repo: StrategyConfigRepository`, `ingestion_service: MarketDataIngestionService`, `timeframe: str = "1d"`, `lookback_bars: int = 200`. Keep backwards-compat by NOT removing existing args. ~5 LoC signature delta.
- [ ] **6.2** Replace the `_placeholder` async closure with a `_propose_for_routine(routine_name)` factory per design §2.11. Per-symbol try/except + log + continue (FR isolation). ~50 LoC.
- [ ] **6.3** Add the NEW `market_data_sync` routine: `cron_kwargs={"hour": 6, "minute": 0, "day_of_week": "mon-fri"}` + `_ingest_market_data` async closure that calls `ingestion_service.sync(invoked_by="daemon-cron", ...)` with rate-limit + general exception handling. ~30 LoC.
- [ ] **6.4** Update orchestration tests to pass the new constructor args. Existing tests likely call `bootstrap_routines` with the old signature; add new args (or use defaults via factory fixtures). ~20 LoC test updates.

## 7. CLI subcommand `market_data.py`

- [ ] **7.1** Author `apps/api/src/iguanatrader/cli/market_data.py` per design §2.12. Typer app with `sync` + `backfill` subcommands. Lazy imports per gotcha #29. Constructs ingestion service the same way the daemon does (separate IBKR connection lifecycle for the CLI process). ~120 LoC.
- [ ] **7.2** Surface `MarketDataRateLimitedError` as `typer.Exit(2)` with stderr message `"Rate limit exceeded: ..."`. Operator UX: clear non-zero exit + actionable message.

## 8. Daemon wiring (`cli/trading.py`)

- [ ] **8.1** Construct the new components after `risk_service.register_subscriptions(bus)` + `approval_service.register_subscriptions(bus)`: `DBMarketDataAdapter()`, `StrategyConfigRepository()`, `IbAsyncMarketDataIngestor(ib_client=ib_client)` (SHARES with broker), `MarketDataSyncAuditRepository()`, `MarketDataIngestionService(ingestor=..., audit_repo=...)`. ~15 LoC.
- [ ] **8.2** Pass them into `orchestration_service.bootstrap_routines(...)` (existing call). ~5 LoC update.
- [ ] **8.3** Update `_make_strategy_resolver` callsite to pass `session_factory=sessionmaker`. ~2 LoC.

## 9. Tests

### 9.1 Unit tests

- [ ] **9.1.1** `apps/api/tests/unit/contexts/trading/market_data/test_in_memory_adapter.py` — 3 tests (seeded symbol returns expected, unseeded raises, lookback > seed returns whole). ~80 LoC.
- [ ] **9.1.2** `test_db_adapter.py` — 3 tests (empty table → error, 250 rows → returns last 200 sorted asc, tenant isolation). Uses real sqlite session via the existing `engine` fixture pattern. ~120 LoC.
- [ ] **9.1.3** `test_ingestion_service.py` — 6 tests (success, partial, full failure, rate-limited, env-var override, audit timing). AsyncMock for ingestor. ~200 LoC.
- [ ] **9.1.4** `apps/api/tests/unit/contexts/trading/test_strategy_resolver_async.py` — 2 tests (resolver returns matching strategy, missing config raises LookupError). ~60 LoC.

### 9.2 Integration test

- [ ] **9.2.1** `apps/api/tests/integration/test_trading_pipeline_e2e.py::test_propose_to_fill_chain` — the canonical end-to-end. Uses `InMemoryMarketDataAdapter`, real `MessageBus`, real sqlite, all 3 services with `register_subscriptions`. ~250 LoC.
- [ ] **9.2.2** Helper module `tests/integration/_helpers/synthetic_bars.py` with `_generate_uptrend(n)` + `FakeBroker` + `_make_test_resolver`. ~80 LoC.

### 9.3 CLI smoke

- [ ] **9.3.1** `tests/unit/cli/test_market_data_cli.py` — 2 tests (`--help` works, `sync --symbols=...` calls service with expected args). Uses `typer.testing.CliRunner`. ~50 LoC.

## 10. Lint + mypy

- [ ] **10.1** Run `python -m ruff check --fix` on all modified + new files.
- [ ] **10.2** Run `python -m black` on the same set.
- [ ] **10.3** Run `python -m mypy --strict --no-incremental` on:
  - `apps/api/src/iguanatrader/contexts/trading/market_data/` (Port + 3 adapters + service + repo)
  - `apps/api/src/iguanatrader/contexts/trading/ports.py` (Port addition)
  - `apps/api/src/iguanatrader/contexts/trading/repository.py` (2 new methods)
  - `apps/api/src/iguanatrader/contexts/trading/service.py` (StrategyResolver async signature + await)
  - `apps/api/src/iguanatrader/contexts/orchestration/service.py` (bootstrap_routines signature)
  - `apps/api/src/iguanatrader/persistence/models.py` (2 new models)
  - `apps/api/src/iguanatrader/cli/trading.py` (daemon wiring)
  - `apps/api/src/iguanatrader/cli/market_data.py` (NEW)
  - All new + updated test files

## 11. Commit + PR + retro stub

- [ ] **11.1** Branch `slice/t4-followup-market-data` → push → open PR.
- [ ] **11.2** PR body: §4.5 self-review marker block + linked checklist for the 11 task groups.
- [ ] **11.3** Author forward-retro stub `retros/t4-followup-market-data.md`. Pre-flag candidates:
  - Pattern recurrence-3 confirms playbook promotion of "skeleton-then-fill"
  - Protocol+InTreeFake+DeferredProductionInstall canonical (all 3 adapters shipped together, no deferral)
  - Async signature change in T4 archive (`StrategyResolver`) — first time we modify a recently-archived surface; documented as "minimum viable archive touch"
  - Rate-limit via append-only audit table (vs in-memory token bucket) — observable + cross-process safe by design
  - Migration slot `0012` claimed pre-emptively in proposal.md per playbook v0.11 lesson

---

## Estimated effort

| Group | Files (NEW + MOD) | Effort | LoC |
|---|---|---|---|
| 1 Models + migration | `models.py` (+~55) + `0012_market_data_tables.py` (NEW ~80) | 1.5h | ~135 |
| 2 Port + 3 adapters | `ports.py` (+~50) + `market_data/{in_memory,db,ibkr_ingestor}.py` (NEW ~210) | 2h | ~260 |
| 3 IngestionService + audit repo | `market_data/{service,repository}.py` (NEW ~160) | 1h | ~160 |
| 4 StrategyConfig repo methods | `repository.py` (+~20) | 0.25h | ~20 |
| 5 Strategy resolver async signature | `service.py` (+~3) + test updates (+~30) + `cli/trading.py` (+~25) | 1h | ~58 |
| 6 bootstrap_routines update | `orchestration/service.py` (+~85) + tests (+~20) | 1.5h | ~105 |
| 7 CLI `market-data` subcommand | `cli/market_data.py` (NEW ~120) | 1h | ~120 |
| 8 Daemon wiring | `cli/trading.py` (+~22) | 0.5h | ~22 |
| 9 Tests | 5 NEW unit files + 1 integration + 1 helper | 3h | ~840 |
| 10 Lint + mypy | (cleanup pass) | 0.5h | – |
| 11 PR + retro | branch + PR + retro stub | 0.5h | ~80 |

**Total**: ~12.5h sequential. **Net new LoC**: ~1800 (≈900 src + ~840 tests + ~80 retro/openspec docs). Note: ~900 src is on the upper end of the proposal's `~900-1000` estimate due to 6 unit tests for IngestionService alone.

**Blast radius**: 1 archive-surface signature change (T4 `StrategyResolver` → async). All other modifications are additive: NEW package + NEW migration + NEW CLI subcommand + 2 new repo methods + 1 method body fill + 2 method body fills (orchestration + daemon wiring). K1+P1 bridge surfaces UNTOUCHED.

**Carry-forward** (next slice candidates):
- `trades-read-endpoints` — fill the 3 stub trade/order GET endpoints (501 → bodies). Independent of this slice.
- `market-data-replay` — operator CLI `iguanatrader market-data replay --routine=midday --date=2026-04-15` to replay a past tick. Schema enables it.
- `intraday-market-data` — `1m` / `1h` timeframe support + per-strategy timeframe override. v2 SaaS.
- `per-tenant-watchlist-table` — replace env-var with `watchlists` table. v2 SaaS.
