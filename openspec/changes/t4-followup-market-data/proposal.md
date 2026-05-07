# Proposal: t4-followup-market-data

> **Closes the T4 keystone definitively**: ships the `MarketDataPort` abstraction + 3 adapters (InMemory for tests, DB-backed for production reads, IBKR-backed for production writes), the `market_data_bars` storage table, a daily ingestion routine + user-invocable CLI sync/backfill commands, fills the strategy resolver, and adds the long-deferred end-to-end integration test that validates K1+P1 bridges + propose loops in a single run.

## Why

T4 (PR #102, merged 2026-05-07) shipped the keystone partial: 6 handler bodies, daemon entrypoint, scheduler+broker DI, manual-approve operator override. K1-followup (PR #103) + P1-followup (PR #104) closed the bus-bridge gaps. **What's still missing**: the daemon is operationally inert. Cron ticks fire `_placeholder()` no-ops; there is no production path that synthesises a `TradeProposal` because:

1. **`_make_strategy_resolver` raises NotImplementedError** — strategies cannot resolve from a config id at runtime.
2. **`bootstrap_routines` registers placeholder closures** — the 4 cron routines tick correctly but evaluate nothing.
3. **No bars source exists**. `TradingService.propose(symbol, strategy_config_id, bars, config)` requires a `BarHistory` arg; nothing in the codebase fetches bars for a given symbol. T4 deferred this to a "bars-fetcher" slice.
4. **No production trigger path**. The only way to inject a proposal today is the manual-approve operator override (which bypasses K1+P1 entirely).

Without bars storage, the daemon must call IBKR live every cron tick — but IBKR has hard pacing limits (60 historic-bar requests / 10-min sliding window; banned for hours if exceeded), so a per-tick live call is operationally fragile. **Decoupling fetch from evaluation via a DB cache solves pacing, enables backtest/replay, makes CI testable without IBKR Gateway, and simplifies dev workflow.**

After this slice ships, the keystone is complete: daemon boots → ingestor refills `market_data_bars` daily → cron routines read from DB → strategies evaluate → proposals flow through K1+P1 bridges → broker fills (paper). End-to-end integration test exercises the full chain in CI without IBKR connectivity.

## Architecture

```
                        ┌──────────────────────────────┐
                        │  market_data_bars (table)     │
                        │  PK: (tenant, sym, tf, ts)    │
                        │  UPSERT on conflict           │
                        └──────────────────────────────┘
                            ▲                       │
                  INSERT    │                       │ SELECT
                            │                       ▼
              ┌─────────────────────┐    ┌─────────────────────┐
              │ IbAsyncBarsIngestor │    │ DBMarketDataAdapter │
              │ (writer)            │    │ (reader, prod)      │
              └─────────────────────┘    └─────────────────────┘
                            ▲                       ▲
                            │ uses                  │ implements
                  ┌─────────────────────┐ ┌─────────────────────┐
                  │ MarketDataIngestion │ │  MarketDataPort     │◀──── propose loops
                  │ Service             │ └─────────────────────┘      read here
                  └─────────────────────┘           ▲
                            ▲                       │ also implements
                  ┌─────────┴───────────┐ ┌─────────────────────┐
                  │ Cron routine        │ │ InMemoryAdapter     │
                  │ "market_data_sync"  │ │ (tests/dev)         │
                  │ daily 06:00 ET      │ └─────────────────────┘
                  │ (5th routine)       │
                  └─────────────────────┘
                            ▲
                            │ AND ALSO
                  ┌─────────────────────┐
                  │ CLI subcommands     │
                  │ - market-data sync  │
                  │ - market-data       │
                  │   backfill          │
                  └─────────────────────┘
                            │
                   rate-limited via
                            ▼
              ┌──────────────────────────────┐
              │ market_data_sync_audit       │
              │ (append-only invocation log) │
              └──────────────────────────────┘
```

## What

Six additive components; one new migration; zero archive-surface modification:

### 1. `MarketDataPort` Protocol (`apps/api/src/iguanatrader/contexts/trading/ports.py`)

Adds a Protocol with the canonical fetch signature:

```python
class MarketDataPort(Protocol):
    async def get_bars(
        self,
        *,
        symbol: str,
        timeframe: Literal["1d", "1h", "1m"],
        lookback_bars: int,
    ) -> BarHistory: ...
```

`BarHistory` already exists in `ports.py` (T1). Returning the latest `lookback_bars` bars sorted ascending by `ts`. Raises `MarketDataNotAvailableError` if the table has zero rows for the symbol+timeframe (callers handle gracefully — log + skip the symbol).

### 2. Three adapters (`apps/api/src/iguanatrader/contexts/trading/market_data/`)

NEW package directory:

- **`InMemoryMarketDataAdapter`** (`in_memory.py`): seeded constructor `(seed: dict[str, list[Bar]])`; tests pass synthetic bars; raises `MarketDataNotAvailableError` if symbol absent.
- **`DBMarketDataAdapter`** (`db.py`): SELECT-only adapter. Reads session from `session_var`. Returns `BarHistory` from `market_data_bars` filtered by tenant + symbol + timeframe + ORDER BY ts DESC LIMIT lookback_bars + reversed.
- **`IbAsyncMarketDataIngestor`** (`ibkr_ingestor.py`): NOT a `MarketDataPort` implementor — it's the *writer*. Uses the same `IbAsyncIBClient` connection that broker uses (or a separate one — see Open Question below). Method `ingest(symbols: list[str], timeframe: str, lookback_bars: int) -> IngestResult`: calls `reqHistoricalDataAsync` per symbol with a `0.5s` inter-request sleep + an asyncio.Semaphore(1) wrapper for concurrent safety. UPSERTs results into `market_data_bars`. Returns `(successes, failures, total_bars_written)`.

### 3. `market_data_bars` table + migration (`0012_market_data_tables.py`)

**Migration slot reserved**: `0012` (latest is `0011_orchestration_tables.py`). Per [migration-slot-reservation.md](../../../.ai-playbook/specs/migration-slot-reservation.md).

```python
class MarketDataBar(Base):
    __tablename__ = "market_data_bars"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "symbol", "timeframe", "ts"),
        Index("market_data_bars_lookup", "tenant_id", "symbol", "timeframe", "ts"),
    )
```

**Mutable** (per Gate A decision 3c): no `__append_only_mutable_columns__` declaration; UPSERT on conflict via SQLAlchemy `Insert.on_conflict_do_update`. Rationale: IBKR may ship adjusted prices for splits/dividends post-fact; mutability lets us re-ingest safely without a separate `adjusted` flag dance.

**Companion table `market_data_sync_audit`**: same migration. Append-only log of every ingestor invocation:

```python
class MarketDataSyncAudit(Base):
    __tablename__ = "market_data_sync_audit"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    invoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invoked_by: Mapped[str] = mapped_column(String(32), nullable=False)  # 'daemon-cron' | 'cli-sync' | 'cli-backfill'
    symbols: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    lookback_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # 'success' | 'partial' | 'failed' | 'rate_limited'
    bars_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (Index("market_data_sync_audit_recent", "tenant_id", "invoked_at"),)
```

Strict-append-only (uses `__append_only_mutable_columns__ = ()`). Used for rate-limit checks + ops dashboards.

### 4. `MarketDataIngestionService` (`apps/api/src/iguanatrader/contexts/trading/market_data/service.py`)

Domain service that wraps the ingestor with rate-limiting + audit-write logic:

```python
class MarketDataIngestionService:
    def __init__(self, *, ingestor: IbAsyncMarketDataIngestor, audit_repo: MarketDataSyncAuditRepository) -> None: ...

    async def sync(
        self,
        *,
        symbols: list[str],
        timeframe: str = "1d",
        lookback_bars: int = 200,
        invoked_by: Literal["daemon-cron", "cli-sync", "cli-backfill"],
    ) -> IngestResult:
        # 1. Check rate limit: count audit rows in last hour, refuse if >= MAX_INVOCATIONS_PER_HOUR
        # 2. Call ingestor.ingest(...) wrapped in try/except
        # 3. INSERT audit row with status + bars_written + duration + error
        # 4. Return IngestResult to caller
```

**Rate-limit rule**: `IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR` env-var (default `10`). Daemon's daily cron consumes 1/hour; CLI users have 9 free invocations/hour. On exceeded: raise `MarketDataRateLimitedError` (HTTP 429-equivalent for the CLI) without calling IBKR. Audit row still written with `status='rate_limited'` so ops can see who's spamming.

### 5. Daemon wiring (`apps/api/src/iguanatrader/cli/trading.py`)

- Construct `DBMarketDataAdapter(session=session)` and pass it into `OrchestrationService.bootstrap_routines(market_data_port=...)`.
- Construct `IbAsyncMarketDataIngestor(ib_client=ib_client)` (reuses the broker's IBKR connection — see Open Question 1) + `MarketDataIngestionService` + register a 5th cron routine `market_data_sync` daily at 06:00 ET that calls `ingestion_service.sync(symbols=watchlist_symbols, ..., invoked_by="daemon-cron")`.

### 6. Per-symbol propose loops (`apps/api/src/iguanatrader/contexts/orchestration/service.py`)

`bootstrap_routines` accepts a new `market_data_port: MarketDataPort` arg. Replaces `_placeholder` with a `_propose_for_routine(routine_name)` factory that:

```python
async def _propose():
    for symbol in watchlist_symbols:
        try:
            configs = await strategy_config_repo.list_enabled_for_tenant_and_symbol(symbol)
            if not configs:
                continue
            bars = await market_data_port.get_bars(symbol=symbol, timeframe="1d", lookback_bars=200)
            for config in configs:
                snapshot = StrategyConfigSnapshot.from_row(config)
                await trading_service.propose(symbol=symbol, strategy_config_id=config.id, bars=bars, config=snapshot)
        except Exception as exc:
            log.warning("orchestration.routine.symbol_failed", symbol=symbol, routine=routine_name, error=str(exc))
            continue
```

Failure isolation: one bad symbol does not skip the rest. `MarketDataNotAvailableError` is the most common case (new symbol added to watchlist before first ingestion) — gets logged + skipped.

### 7. Strategy resolver fill (`apps/api/src/iguanatrader/cli/trading.py`)

NEW method `StrategyConfigRepository.get_by_id(strategy_config_id) -> StrategyConfig | None`. Daemon's `_make_strategy_resolver` closure replaces `NotImplementedError` with: load via `repo.get_by_id` → project to snapshot → `manager._get_or_build(snapshot)`. Closure caches manager instance.

### 8. CLI subcommands (`apps/api/src/iguanatrader/cli/market_data.py` NEW)

```
iguanatrader market-data sync     [--symbols=AAPL,MSFT] [--timeframe=1d] [--lookback-bars=200]
iguanatrader market-data backfill --symbol AAPL [--days 365] [--timeframe=1d]
```

Both invoke `MarketDataIngestionService.sync(...)` with appropriate `invoked_by` values and lookback-bars derivation. `backfill` is just a sync with a much-larger `lookback_bars` (= `days × bars_per_day` for the timeframe).

Both subcommands respect the same rate-limit (audit-table check) and surface a clear error if exceeded.

### 9. Integration test (`apps/api/tests/integration/test_trading_pipeline_e2e.py` NEW)

Single-process test:
- Spins up sqlite (aiosqlite) + tenant context + bus + `InMemoryMarketDataAdapter` seeded with 200 days of synthetic bars per symbol.
- Constructs `TradingService` + `RiskService` + `ApprovalService` + calls all 3 `register_subscriptions(bus)`.
- Stubs `BrokerPort` with a `FakeBroker` recording `place_order` calls.
- Triggers a midday-equivalent tick: directly calls `_propose_for_routine("midday")` (the closure factory) for `["AAPL"]` watchlist.
- Synthesises an `ApprovalProposalApproved` to simulate operator approval.
- Drains bus.
- Asserts: 1 ProposalCreated + 1 ProposalRiskEvaluated(allow) + 1 ApprovalRequested + 1 approval_requests row INSERTed + 1 ApprovalProposalApproved + 1 trading.ProposalApproved + 1 OrderPlaced + 1 broker.place_order call + correct order shape.

## Out of scope

- **Live-mode IBKR connection lifecycle** — existing IbAsyncIBClient adapter handles. The ingestor reuses that connection.
- **Intraday timeframes** (`1m`, `1h`) — schema supports them via `timeframe` column, but the v1 watchlist + cron routines hardcode `"1d"`. v2 SaaS slice can add intraday.
- **Per-tenant timezone for the daily cron** — APScheduler default UTC; v2 swaps.
- **Replay/backtest CLI** — schema enables it (immutable history), but the `iguanatrader market-data replay --routine=midday --date=2026-04-15` command is a future micro-slice.
- **Trade/order read endpoints** (`GET /trades/{id}`, etc.) — separate slice `trades-read-endpoints`.
- **Adjusted-price reconciliation** — UPSERT covers re-ingest, but a dedicated split/dividend reconciler is a SaaS concern.

## Acceptance criteria

Code-level (verified by tests + CI):

1. `MarketDataPort` Protocol is declared; 3 adapters implement (or interact with) it; mypy --strict passes.
2. `0012_market_data_tables.py` migration applies forward + backward cleanly; alembic roundtrip test green.
3. `_make_strategy_resolver` body resolves a `UUID → StrategyPort` (no `NotImplementedError`); replaced.
4. `bootstrap_routines` accepts `market_data_port` arg + replaces `_placeholder` with the factory; 4 routines wire real propose loops + the 5th `market_data_sync` routine wires the ingestor.
5. `MarketDataIngestionService.sync(...)` + the audit table + rate-limit logic are exercised by ≥6 unit tests covering: success path, partial failure (1 of 3 symbols), full failure, rate-limited refusal, audit row written for each branch.
6. CLI subcommands `iguanatrader market-data sync` + `market-data backfill` work + respect the rate limit.
7. End-to-end integration test passes (validates K1+P1 bridges + propose loops + broker fill).
8. mypy --strict + ruff + black + pre-commit + CI all green.

Operator-driven (verified post-merge):

9. Paper-mode daemon boots → 06:00 ET tick fires market_data_sync → bars appear in `market_data_bars` for watchlist symbols → midday tick fires propose loops → proposals + orders flow through bus + paper broker.

## Pattern usage

- **Protocol + InTreeFake + DeferredProductionInstall** (ai-playbook v0.11): canonical use here — `MarketDataPort` Protocol + `InMemoryMarketDataAdapter` (in-tree fake) + `DBMarketDataAdapter` (production read) + `IbAsyncMarketDataIngestor` (production write). Not deferred — all four ship simultaneously.
- **Skeleton-then-fill** (T4 retro lesson): T1 declared `_make_strategy_resolver` + `bootstrap_routines._placeholder` skeletons; this slice fills both bodies. **Third recurrence** of the pattern (R1→R5, T1→T4, T1+T4→t4-followup-market-data); justifies playbook v0.11.1 promotion.
- **Bus-bridge follow-up validation**: integration test is the *first* end-to-end execution of the K1-followup + P1-followup bridges. A green test confirms both bridge slices ship as designed.

## Migration slot reservation

| Slot | Migration | Tables |
|---|---|---|
| 0012 | `0012_market_data_tables.py` | `market_data_bars`, `market_data_sync_audit` |

Per [migration-slot-reservation.md](../../../.ai-playbook/specs/migration-slot-reservation.md): claim made at proposal time; latest existing slot is `0011`. No collision risk (no other parallel slice claims this range).

## Open questions

1. **IBKR connection sharing**: should `IbAsyncMarketDataIngestor` share the broker's `IbAsyncIBClient` connection or open its own? Sharing avoids 2x TCP sockets but couples shutdown (broker disconnect kills ingestor mid-fetch). Lean: **share** for v1 (1 IBKR session per daemon process); revisit if a contention bug appears. Confirmed at design time (Gate B).

2. **Default timeframe for v1**: hardcode `"1d"` in propose loops + ingestor or allow per-strategy override? Lean: **hardcode `"1d"`**; expose as env-var if a strategy needs `"1h"` later.

3. **Schema refinement**: should `tenant_id` be NULL-allowed in `market_data_bars` (price data is the same across all tenants for a given exchange)? Lean: **keep NOT NULL** for consistency with the rest of the schema + simplicity of the tenant-listener; storage cost is negligible (3 tenants = 3x rows for same data; this is fine until tenant count grows). Revisit at v2 SaaS.

These become design-time decisions in Gate B.

## Blast radius

- **NEW package**: `apps/api/src/iguanatrader/contexts/trading/market_data/` (Port + 3 adapters + service + audit repo).
- **NEW migration**: `0012_market_data_tables.py` (2 tables).
- **NEW CLI subcommand**: `apps/api/src/iguanatrader/cli/market_data.py` (registered alongside `cli/trading.py`).
- **MODIFIED**: `cli/trading.py` (daemon wiring), `contexts/orchestration/service.py` (`bootstrap_routines`), `contexts/trading/repository.py` (`StrategyConfigRepository.get_by_id`).
- **NEW test**: `tests/integration/test_trading_pipeline_e2e.py`.
- **Archive surfaces UNTOUCHED**: K1 risk service, P1 approval service, T1+T4 trading service, R1 research, O1 observability, deployment-foundation adapters. All existing unit + integration tests continue to pass.

Estimated effort: ~12h sequential, ~900-1000 LoC (~250 src for Port+adapters+service, ~120 for migration+models, ~200 for daemon+CLI wiring + propose loops, ~330 for tests + integration test, ~100 for retro/openspec docs).
