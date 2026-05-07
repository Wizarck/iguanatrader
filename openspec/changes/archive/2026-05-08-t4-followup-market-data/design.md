# Design — t4-followup-market-data

> **Purpose**: ship the market-data fetching/storage subsystem that closes the T4 keystone definitively. Decouples bars-fetching (IBKR-driven, scheduled) from strategy evaluation (DB-read on every cron tick). Enables the long-deferred end-to-end integration test by providing an InMemory adapter that satisfies CI without IBKR connectivity.
>
> **Pattern reference**: this is the third canonical instance of "**skeleton-then-fill**" (R1→R5, T1→T4, T1+T4→THIS) plus a fresh canonical of "**Protocol + InTreeFake + DeferredProductionInstall**" (Port + 3 adapters all shipped together — *not* deferred).

## 1. Pipeline context

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         WRITE PATH (daily / on-demand)                       │
│                                                                              │
│   ┌────────────────┐      ┌─────────────────────────┐    ┌─────────────────┐ │
│   │ Cron routine   │─────▶│ MarketDataIngestion     │───▶│ IbAsyncMarket   │ │
│   │ "market_data_  │      │ Service                 │    │ DataIngestor    │ │
│   │  sync" daily   │      │ (rate-limit + audit)    │    │ (IBKR adapter)  │ │
│   │  06:00 UTC     │      └─────────────────────────┘    └─────────────────┘ │
│   └────────────────┘                ▲                            │           │
│                                     │                            │ IBKR HIST │
│                                     │                            │ DATA      │
│   ┌────────────────┐                │                            ▼           │
│   │ CLI            │────────────────┘             ┌──────────────────────────┴──┐
│   │ market-data    │                              │  market_data_bars (table)   │
│   │  sync          │                              │  PK: (tenant, sym, tf, ts)  │
│   │  backfill      │                              │  UPSERT on conflict         │
│   └────────────────┘                              └──────────────────────────┬──┘
│                                                                              │
│                                                          Audit each call     │
│                                                          ▼                   │
│                              ┌─────────────────────────────────────────────┐ │
│                              │  market_data_sync_audit (append-only)        │ │
│                              │  used for rate-limit + ops dashboards        │ │
│                              └─────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                         READ PATH (every cron tick)                          │
│                                                                              │
│   ┌────────────────┐                            ┌──────────────────────────┐ │
│   │ Cron routines  │                            │  DBMarketDataAdapter     │ │
│   │ premarket      │───▶  bootstrap_routines  ─▶│  (impl MarketDataPort)   │ │
│   │ midday         │      _propose_for_routine  │  SELECT FROM             │ │
│   │ postmarket     │      iterates symbols      │   market_data_bars       │ │
│   │ weekly_review  │                            │  ORDER BY ts DESC LIMIT N│ │
│   └────────────────┘                            └──────────────────────────┘ │
│                              │                                               │
│                              ▼                                               │
│                  await get_bars(symbol, "1d", 200)                           │
│                              │                                               │
│                              ▼                                               │
│              for symbol, config in (watchlist × enabled configs):            │
│                  await trading_service.propose(symbol, config_id, bars,      │
│                                                snapshot)                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Critical invariants**:
- The propose loops do NOT call IBKR directly. Read path = DB only. Write path = IBKR via scheduled ingestor.
- `MarketDataNotAvailableError` (raised when `market_data_bars` has no rows for a symbol) is logged + skipped per-symbol; one missing symbol does not skip the rest of the watchlist (FR isolation).
- The ingestor's IBKR connection is **shared with the broker's `IbAsyncIBClient`** (Open Question 1 resolved: SHARE). Daemon constructs one `IbAsyncIBClient` and passes it to both `IBKRAdapter` (broker) and `IbAsyncMarketDataIngestor` (writer). Cron schedule prevents temporal overlap (06:00 UTC ingestor vs 08:00+ UTC propose loops).
- The audit table is the single source of truth for rate-limiting. Daemon cron writes 1 audit row/day; CLI users get `MAX_INVOCATIONS_PER_HOUR=10` minus daemon's 1-per-hour effective budget.

## 2. Per-component specifications

### 2.1 `MarketDataPort` Protocol (`apps/api/src/iguanatrader/contexts/trading/ports.py`)

```python
from typing import Literal, Protocol


class MarketDataPort(Protocol):
    """Read-only port for fetching historical bars (slice T4-followup).

    Production daemons use :class:`DBMarketDataAdapter` (reads from
    ``market_data_bars`` populated by the IBKR ingestor). Tests use
    :class:`InMemoryMarketDataAdapter` (seeded synthetic bars). The
    daemon's read path is decoupled from the IBKR connection — bars
    are populated asynchronously by the daily ``market_data_sync``
    cron routine OR by the ``iguanatrader market-data sync`` CLI.
    """

    async def get_bars(
        self,
        *,
        symbol: str,
        timeframe: Literal["1d", "1h", "1m"],
        lookback_bars: int,
    ) -> BarHistory:
        """Return the last ``lookback_bars`` bars sorted ascending by ts.

        Raises :class:`MarketDataNotAvailableError` if zero bars exist
        for the (tenant, symbol, timeframe) tuple. Callers handle by
        logging + skipping the symbol.
        """
        ...
```

`BarHistory` already exists at `ports.py:129` (T1) — `BarHistory(symbol: str, bars: Sequence[Bar])`. The Port returns it unchanged.

`MarketDataNotAvailableError` is a NEW domain error class declared in `apps/api/src/iguanatrader/contexts/trading/errors.py` (or its colocated equivalent — TBD at apply time). Inherits from `IguanaError` per slice-5 RFC 7807 contract.

### 2.2 `InMemoryMarketDataAdapter` (`apps/api/src/iguanatrader/contexts/trading/market_data/in_memory.py`)

```python
class InMemoryMarketDataAdapter:
    """Test/dev adapter — returns bars from an in-memory dict.

    Constructor seeds a `{symbol: list[Bar]}` map. Used by:
    - integration tests (test_trading_pipeline_e2e.py)
    - dev workflows where running IBKR Gateway locally is friction
    """
    def __init__(self, *, seed: dict[str, list[Bar]]) -> None:
        self._seed = seed

    async def get_bars(
        self, *, symbol: str, timeframe: Literal["1d", "1h", "1m"], lookback_bars: int,
    ) -> BarHistory:
        if symbol not in self._seed:
            raise MarketDataNotAvailableError(
                detail=f"No seeded bars for symbol={symbol!r}",
            )
        bars = self._seed[symbol][-lookback_bars:]
        return BarHistory(symbol=symbol, bars=bars)
```

The seed map is constructed by tests via a synthetic-bar generator (linear uptrend so Donchian breaks).

### 2.3 `DBMarketDataAdapter` (`apps/api/src/iguanatrader/contexts/trading/market_data/db.py`)

Production read adapter. Reads `session_var` lazily per `BaseRepository` convention.

```python
class DBMarketDataAdapter:
    """Production read adapter — SELECT from market_data_bars."""

    async def get_bars(
        self, *, symbol: str, timeframe: Literal["1d", "1h", "1m"], lookback_bars: int,
    ) -> BarHistory:
        session = session_var.get()
        if session is None:
            raise LookupError("session_var not set; cannot read market_data_bars")
        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            raise LookupError("tenant_id_var not set; cannot read market_data_bars")
        stmt = (
            select(MarketDataBar)
            .where(MarketDataBar.tenant_id == tenant_id)
            .where(MarketDataBar.symbol == symbol)
            .where(MarketDataBar.timeframe == timeframe)
            .order_by(MarketDataBar.ts.desc())
            .limit(lookback_bars)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if not rows:
            raise MarketDataNotAvailableError(
                detail=f"No bars in DB for tenant={tenant_id}, symbol={symbol}, "
                       f"timeframe={timeframe}",
            )
        rows.reverse()  # caller expects ascending ts
        bars = [
            Bar(ts=r.ts, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume)
            for r in rows
        ]
        return BarHistory(symbol=symbol, bars=bars)
```

### 2.4 `IbAsyncMarketDataIngestor` (`apps/api/src/iguanatrader/contexts/trading/market_data/ibkr_ingestor.py`)

Production write adapter. NOT a `MarketDataPort` impl (it writes; doesn't read). Shares the broker's `IbAsyncIBClient` connection.

```python
class IbAsyncMarketDataIngestor:
    """Calls IBKR reqHistoricalDataAsync + UPSERTs into market_data_bars.

    Pacing strategy (per ib_async + IBKR docs):
    - asyncio.Semaphore(1): only 1 in-flight request at a time
    - 0.5s sleep between requests: keeps under 6-per-2s limit
    - 200 daily bars in one request: 1 fetch per symbol (no pagination)

    Failure modes:
    - Pacing violation from IBKR: caught + retry once after 5s sleep;
      second failure raises MarketDataPacingViolation
    - Connection drop: ib_async surfaces ConnectionError; raised to caller
    - Unknown contract (delisted ticker): logged + skipped, NO row written
    """

    def __init__(self, *, ib_client: IbAsyncIBClient) -> None:
        self._ib_client = ib_client
        self._semaphore = asyncio.Semaphore(1)
        self._inter_request_sleep = 0.5  # seconds

    async def ingest(
        self,
        *,
        symbols: list[str],
        timeframe: str = "1d",
        lookback_bars: int = 200,
    ) -> IngestResult:
        """Fetch + UPSERT per-symbol; returns aggregate stats."""
        successes: list[str] = []
        failures: list[tuple[str, str]] = []
        bars_written = 0
        for symbol in symbols:
            async with self._semaphore:
                try:
                    bars = await self._fetch(symbol, timeframe, lookback_bars)
                    written = await self._upsert(symbol, timeframe, bars)
                    successes.append(symbol)
                    bars_written += written
                except Exception as exc:
                    failures.append((symbol, str(exc)))
                    log.warning(
                        "market_data.ingest.symbol_failed",
                        symbol=symbol, timeframe=timeframe, error=str(exc),
                    )
                await asyncio.sleep(self._inter_request_sleep)
        return IngestResult(successes=successes, failures=failures, bars_written=bars_written)

    async def _fetch(self, symbol: str, timeframe: str, lookback_bars: int) -> list[Bar]:
        # Builds a Stock contract via ib_client.qualify_contract(symbol);
        # calls reqHistoricalDataAsync with durationStr derived from
        # lookback_bars + timeframe; returns ib_async BarData → Bar dataclass.
        ...

    async def _upsert(self, symbol: str, timeframe: str, bars: list[Bar]) -> int:
        # SQLAlchemy Insert(MarketDataBar.__table__).on_conflict_do_update(
        #   index_elements=["tenant_id", "symbol", "timeframe", "ts"],
        #   set_=dict(open=..., high=..., low=..., close=..., volume=...,
        #             source=..., fetched_at=...)
        # ).
        # Returns row count from result.rowcount.
        ...
```

**Note on `IngestResult`**: a dataclass with `successes: list[str]`, `failures: list[tuple[str, str]]`, `bars_written: int`, `duration_ms: int`. Used both as the ingestor's return value AND as the audit table's payload source.

### 2.5 `MarketDataIngestionService` (`apps/api/src/iguanatrader/contexts/trading/market_data/service.py`)

Orchestrates the ingestor with rate-limiting + audit-write.

```python
class MarketDataIngestionService:
    """Domain service wrapping the ingestor + audit + rate-limit logic."""

    DEFAULT_MAX_INVOCATIONS_PER_HOUR = 10

    def __init__(
        self,
        *,
        ingestor: IbAsyncMarketDataIngestor,
        audit_repo: MarketDataSyncAuditRepository,
    ) -> None:
        self._ingestor = ingestor
        self._audit_repo = audit_repo

    async def sync(
        self,
        *,
        symbols: list[str],
        timeframe: str = "1d",
        lookback_bars: int = 200,
        invoked_by: Literal["daemon-cron", "cli-sync", "cli-backfill"],
    ) -> IngestResult:
        """Audit-wrapped ingestor call with rate-limit guard."""
        max_invocations = int(os.environ.get(
            "IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR",
            self.DEFAULT_MAX_INVOCATIONS_PER_HOUR,
        ))
        recent_count = await self._audit_repo.count_invocations_since(
            since=utc_now() - timedelta(hours=1),
        )
        if recent_count >= max_invocations:
            await self._audit_repo.write_audit_row(
                invoked_by=invoked_by,
                symbols=symbols,
                timeframe=timeframe,
                lookback_bars=lookback_bars,
                status="rate_limited",
                bars_written=0,
                duration_ms=0,
                error=f"Exceeded {max_invocations} invocations/hour",
            )
            raise MarketDataRateLimitedError(
                detail=f"Rate limit exceeded: {recent_count}/{max_invocations} "
                       f"invocations in the last hour. Wait + retry.",
            )

        start = time.monotonic()
        try:
            result = await self._ingestor.ingest(
                symbols=symbols, timeframe=timeframe, lookback_bars=lookback_bars,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            status = "success" if not result.failures else "partial"
            await self._audit_repo.write_audit_row(
                invoked_by=invoked_by,
                symbols=symbols,
                timeframe=timeframe,
                lookback_bars=lookback_bars,
                status=status,
                bars_written=result.bars_written,
                duration_ms=duration_ms,
                error=None,
            )
            return result
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self._audit_repo.write_audit_row(
                invoked_by=invoked_by,
                symbols=symbols,
                timeframe=timeframe,
                lookback_bars=lookback_bars,
                status="failed",
                bars_written=0,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise
```

`MarketDataRateLimitedError`: NEW domain error inheriting `IguanaError`. CLI translates to a typer.Exit(2) with a clear stderr message.

### 2.6 Migration `0012_market_data_tables.py`

Two tables in one revision. Migration shape follows the slice-3 + slice-T1 conventions.

```python
# Slot 0012 reserved per migration-slot-reservation.md.

revision = "0012_market_data_tables"
down_revision = "0011_orchestration_tables"

def upgrade() -> None:
    op.create_table(
        "market_data_bars",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.BigInteger, nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "symbol", "timeframe", "ts",
                            name="market_data_bars_unique"),
    )
    op.create_index(
        "market_data_bars_lookup",
        "market_data_bars",
        ["tenant_id", "symbol", "timeframe", "ts"],
    )

    op.create_table(
        "market_data_sync_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invoked_by", sa.String(32), nullable=False),
        sa.Column("symbols", postgresql.ARRAY(sa.String), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("lookback_bars", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("bars_written", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index(
        "market_data_sync_audit_recent",
        "market_data_sync_audit",
        ["tenant_id", "invoked_at"],
    )
```

**Sqlite compat note**: `postgresql.ARRAY(sa.String)` doesn't work on sqlite. Migrations + tests must use `sa.JSON` fallback if dialect is sqlite. Standard pattern in this repo (look at the slice-3 migrations for the dialect-conditional ARRAY/JSON code).

`down_revision()` drops both tables in reverse order.

### 2.7 SQLAlchemy models

`apps/api/src/iguanatrader/persistence/models.py` gets two new classes — `MarketDataBar` + `MarketDataSyncAudit`. Both inherit `Base`. The audit class declares `__append_only_mutable_columns__ = ()` to opt into the slice-3 listener (UPDATE/DELETE attempts raise `AppendOnlyViolation`). The bars class does NOT declare it (mutable, UPSERT-friendly).

### 2.8 `MarketDataSyncAuditRepository`

`apps/api/src/iguanatrader/contexts/trading/market_data/repository.py`:

```python
class MarketDataSyncAuditRepository(BaseRepository):
    async def count_invocations_since(self, *, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(MarketDataSyncAudit)
            .where(MarketDataSyncAudit.invoked_at >= since)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def write_audit_row(self, **kwargs: Any) -> MarketDataSyncAudit:
        # tenant_id auto-stamped by tenant_listener; invoked_at = utc_now()
        ...
```

### 2.9 `StrategyConfigRepository.get_by_id`

NEW method on the existing class (`apps/api/src/iguanatrader/contexts/trading/repository.py`).

```python
async def get_by_id(self, strategy_config_id: UUID) -> StrategyConfig | None:
    stmt = select(StrategyConfig).where(StrategyConfig.id == strategy_config_id)
    result = await self.session.execute(stmt)
    return cast("StrategyConfig | None", result.scalars().first())

async def list_enabled_for_tenant_and_symbol(self, symbol: str) -> list[StrategyConfig]:
    stmt = (
        select(StrategyConfig)
        .where(StrategyConfig.symbol == symbol)
        .where(StrategyConfig.enabled.is_(True))
    )
    result = await self.session.execute(stmt)
    return list(result.scalars().all())
```

Both rely on the slice-3 `tenant_listener` for automatic tenant scoping.

### 2.10 `_make_strategy_resolver` body fill

`cli/trading.py` — replace the `NotImplementedError` raise with a closure that takes `session` (already in scope) + a `StrategyConfigRepository(session=...)` lookup:

```python
def _make_strategy_resolver(
    *, session_factory: async_sessionmaker[AsyncSession],
) -> StrategyResolver:
    """Closure: UUID → StrategyPort. Loads snapshot via repo + builds via manager."""
    from iguanatrader.contexts.trading.repository import StrategyConfigRepository
    from iguanatrader.contexts.trading.strategies.manager import StrategyManager

    manager = StrategyManager()

    async def _resolve(strategy_config_id: UUID) -> StrategyPort:
        async with session_factory() as session:
            session_var.set(session)
            repo = StrategyConfigRepository()
            row = await repo.get_by_id(strategy_config_id)
            if row is None:
                raise LookupError(
                    f"StrategyConfig {strategy_config_id} not found"
                )
            snapshot = StrategyConfigSnapshot(
                id=row.id, tenant_id=row.tenant_id,
                strategy_kind=row.strategy_kind, symbol=row.symbol,
                params=row.params, enabled=row.enabled, version=row.version,
            )
            strategy = manager._get_or_build(snapshot)
            if strategy is None:
                raise LookupError(
                    f"Unknown strategy_kind {row.strategy_kind!r}"
                )
            return strategy

    return _resolve
```

**Async wrinkle**: T4's `_strategy_resolver` is currently sync (`UUID -> StrategyPort`). The repo call is async. Two options:
- (a) Make `_strategy_resolver` async (callsite in `TradingService.propose` becomes `await self._strategy_resolver(id)`); changes the type alias.
- (b) Resolver returns a sync proxy that lazy-loads on first method call (gross).
- **Decision**: (a). Update the `StrategyResolver` type alias from `Callable[[UUID], StrategyPort]` to `Callable[[UUID], Awaitable[StrategyPort]]` and add `await` at the callsite. T4's tests inject sync resolvers via direct mapping; they'll need a small adapter (one-line `async def _resolve_async(id): return mapping[id]`).

This is the only T4 archive surface that gets touched (signature change in `TradingService.propose`'s `strategy_resolver` arg type). Documented in §3 anti-pattern §3.1.

### 2.11 `bootstrap_routines` per-symbol propose loops + 5th routine

`OrchestrationService.bootstrap_routines` signature changes:

```python
async def bootstrap_routines(
    self,
    *,
    scheduler: object,
    trading_service: object,
    market_data_port: MarketDataPort,           # NEW
    strategy_config_repo: StrategyConfigRepository,  # NEW
    ingestion_service: MarketDataIngestionService,   # NEW
    watchlist_symbols: list[str],
    timeframe: str = "1d",                       # NEW (env-var default)
    lookback_bars: int = 200,                    # NEW
) -> None: ...
```

The 4 existing routines get a real `_propose_for_routine(routine_name)` factory:

```python
def _propose_for_routine(routine_name: str) -> Callable[[], Awaitable[None]]:
    async def _propose() -> None:
        for symbol in watchlist_symbols:
            try:
                configs = await strategy_config_repo.list_enabled_for_tenant_and_symbol(symbol)
                if not configs:
                    continue
                bars = await market_data_port.get_bars(
                    symbol=symbol, timeframe=timeframe, lookback_bars=lookback_bars,
                )
                for config in configs:
                    snapshot = StrategyConfigSnapshot(...)
                    await trading_service.propose(
                        symbol=symbol,
                        strategy_config_id=config.id,
                        bars=bars,
                        config=snapshot,
                    )
            except Exception as exc:
                logger.warning(
                    "orchestration.routine.symbol_failed",
                    extra={"symbol": symbol, "routine": routine_name, "error": str(exc)},
                )
                continue
    return _propose
```

NEW 5th routine `market_data_sync` daily 06:00 UTC mon-fri:

```python
async def _ingest_market_data() -> None:
    try:
        result = await ingestion_service.sync(
            symbols=watchlist_symbols,
            timeframe=timeframe,
            lookback_bars=lookback_bars,
            invoked_by="daemon-cron",
        )
        logger.info(
            "orchestration.market_data_sync.complete",
            extra={"successes": len(result.successes),
                   "failures": len(result.failures),
                   "bars_written": result.bars_written},
        )
    except MarketDataRateLimitedError as exc:
        logger.warning(
            "orchestration.market_data_sync.rate_limited",
            extra={"error": str(exc)},
        )
    except Exception as exc:
        logger.error(
            "orchestration.market_data_sync.failed",
            extra={"error": str(exc)},
        )

cron_kwargs_by_routine["market_data_sync"] = {
    "hour": 6, "minute": 0, "day_of_week": "mon-fri",
}
```

### 2.12 CLI `market_data.py`

`apps/api/src/iguanatrader/cli/market_data.py` — Typer app auto-discovered at kebab-case `market-data`.

```python
import typer

app: typer.Typer = typer.Typer(
    name="market-data",
    help="Market-data ingestion (slice T4-followup). Subcommands: sync, backfill.",
    no_args_is_help=True,
)

@app.command("sync")
def sync(
    symbols: str | None = typer.Option(None, "--symbols", help="CSV. Defaults to env watchlist."),
    timeframe: str = typer.Option("1d", "--timeframe"),
    lookback_bars: int = typer.Option(200, "--lookback-bars"),
    tenant: str | None = typer.Option(None, "--tenant"),
) -> None:
    """Ingest historical bars (rate-limited via market_data_sync_audit)."""
    asyncio.run(_run_sync(symbols=symbols, timeframe=timeframe,
                          lookback_bars=lookback_bars, tenant=tenant,
                          invoked_by="cli-sync"))

@app.command("backfill")
def backfill(
    symbol: str = typer.Option(..., "--symbol"),
    days: int = typer.Option(365, "--days"),
    timeframe: str = typer.Option("1d", "--timeframe"),
    tenant: str | None = typer.Option(None, "--tenant"),
) -> None:
    """Long-window backfill for a single symbol."""
    bars_per_day = {"1d": 1, "1h": 24, "1m": 1440}[timeframe]
    lookback_bars = days * bars_per_day
    asyncio.run(_run_sync(symbols=symbol, timeframe=timeframe,
                          lookback_bars=lookback_bars, tenant=tenant,
                          invoked_by="cli-backfill"))

async def _run_sync(*, symbols: str | None, timeframe: str, lookback_bars: int,
                    tenant: str | None, invoked_by: str) -> None:
    # Constructs ingestion_service the same way the daemon does;
    # calls .sync(); pretty-prints IngestResult; exits 0/2 on rate-limit.
    ...
```

Heavy imports kept inside the command body per gotcha #29.

### 2.13 Daemon wiring (`cli/trading.py`)

Insert after the existing `risk_service.register_subscriptions(bus)` + `approval_service.register_subscriptions(bus)`:

```python
from iguanatrader.contexts.trading.market_data.db import DBMarketDataAdapter
from iguanatrader.contexts.trading.market_data.ibkr_ingestor import IbAsyncMarketDataIngestor
from iguanatrader.contexts.trading.market_data.repository import MarketDataSyncAuditRepository
from iguanatrader.contexts.trading.market_data.service import MarketDataIngestionService
from iguanatrader.contexts.trading.repository import StrategyConfigRepository

market_data_port = DBMarketDataAdapter()
strategy_config_repo = StrategyConfigRepository()
ingestor = IbAsyncMarketDataIngestor(ib_client=ib_client)  # SHARES with broker
audit_repo = MarketDataSyncAuditRepository()
ingestion_service = MarketDataIngestionService(
    ingestor=ingestor, audit_repo=audit_repo,
)
```

Pass them into `bootstrap_routines(...)`.

### 2.14 Integration test (`tests/integration/test_trading_pipeline_e2e.py`)

```python
@pytest.mark.asyncio
async def test_propose_to_fill_chain(
    bus: MessageBus,
    sqlite_session: AsyncSession,
    tenant_id: UUID,
) -> None:
    """End-to-end: synthesise → propose → risk → approve → execute → fill."""
    # 1. Seed strategy_configs (1 enabled donchian_atr for AAPL)
    # 2. Synthesise bars: 200 days linear uptrend so Donchian breaks on tick 200
    in_memory_md = InMemoryMarketDataAdapter(seed={"AAPL": _generate_uptrend(200)})

    # 3. Construct the 3 services + register subscriptions
    fake_broker = FakeBroker()
    trading_service = TradingService(
        bus=bus, broker=fake_broker,
        strategy_resolver=_make_test_resolver(),
    )
    risk_service = RiskService(repository=RiskRepository(session=sqlite_session), bus=bus)
    approval_service = ApprovalService(repository=ApprovalRepository(), message_bus=bus)
    trading_service.register_subscriptions()
    risk_service.register_subscriptions(bus)
    approval_service.register_subscriptions(bus)

    # 4. Trigger a propose: directly call the factory closure (not via cron)
    propose_fn = _make_propose_factory(
        market_data_port=in_memory_md,
        trading_service=trading_service,
        strategy_config_repo=StrategyConfigRepository(),
        watchlist_symbols=["AAPL"],
    )
    await propose_fn()

    # 5. Drain bus (yield N times)
    await _drain(bus, ticks=50)

    # 6. Synthesise an ApprovalProposalApproved (skip the human-in-the-loop)
    approval_event = ApprovalProposalApproved(
        proposal_id=fake_broker.last_proposal_id,
        decision_id=uuid4(),
        decided_at=datetime.now(UTC),
        decided_by_user_id=uuid4(),
        decided_via_channel="telegram",
    )
    await bus.publish(approval_event)
    await _drain(bus, ticks=50)

    # 7. Assert
    assert fake_broker.place_order_calls == 1
    last_call = fake_broker.last_call
    assert last_call.symbol == "AAPL"
    assert last_call.side in ("buy", "sell")
    assert last_call.quantity > 0
    # Plus: 1 ProposalCreated + 1 ProposalRiskEvaluated + 1 ApprovalRequested
    # + 1 trading.ProposalApproved + 1 OrderPlaced events captured.
```

**Helpers**:
- `_generate_uptrend(n)`: returns `n` Bars with linear price increase so Donchian's 20-day breakout fires on tick `n`.
- `_make_test_resolver()`: returns an async closure mapping a known UUID → DonchianATRStrategy instance.
- `_make_propose_factory(...)`: extracted helper that mirrors the production `_propose_for_routine` (or imports it directly).
- `FakeBroker`: implements `BrokerPort` Protocol; records `place_order` calls + emits a synthetic `OrderPlaced` event.

### 2.15 Environment variables

| Var | Type | Default | Notes |
|---|---|---|---|
| `IGUANATRADER_MARKET_DATA_DEFAULT_TIMEFRAME` | string | `"1d"` | Forward-compat for intraday |
| `IGUANATRADER_MARKET_DATA_DEFAULT_LOOKBACK_BARS` | int | `200` | Donchian/SMA fit |
| `IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR` | int | `10` | Rate-limit (audit-checked) |
| `IGUANATRADER_MARKET_DATA_INTER_REQUEST_SLEEP_MS` | int | `500` | Pacing safety on IBKR |

All read at handler-call time (not boot time) so operators can `kubectl set env` + bounce pod.

## 3. Anti-patterns to avoid

1. **Do NOT call IBKR in the propose loops.** The whole point is decoupling. If a symbol's bars are missing in DB, log + skip — let the next ingestion fix it. Calling IBKR inline would re-introduce pacing fragility.
2. **Do NOT skip the audit row on the rate-limited path.** Refusal must be visible to ops dashboards; silent drops are unobservable.
3. **Do NOT make `MarketDataPort` synchronous.** Async all the way; the tenant_listener + session machinery is async-native.
4. **Do NOT introduce a "global tenant" NULL row pattern.** Each tenant gets its own ingested bars rows. Future v2 SaaS slice can introduce a shared cache table when tenant-count > 30.
5. **Do NOT couple the test's `_make_propose_factory` to production code via internal-package imports.** The factory is extracted to a public helper so production + test share one impl. Otherwise test will silently drift.
6. **Do NOT swallow exceptions in `_propose_for_routine`.** Catch + log + continue ONLY for per-symbol failures. Higher-level exceptions (DB connection lost, kill-switch triggered) must propagate to the scheduler so it logs them visibly.
7. **Do NOT use `0:00 UTC` for the daily cron** — UTC midnight is Asian trading hours. `06:00 UTC` is "early enough before US premarket (13:00 UTC EST / 12:00 UTC EDT) to have fresh bars" — pick this.

## 4. Tests

### 4.1 Unit tests (~12 tests)

**`apps/api/tests/unit/contexts/trading/market_data/test_in_memory_adapter.py`** (~3 tests)
- seeded symbol returns expected bars (last N of seed list)
- unseeded symbol raises MarketDataNotAvailableError
- lookback_bars > seed length returns whole seed (no exception)

**`apps/api/tests/unit/contexts/trading/market_data/test_db_adapter.py`** (~3 tests)
- empty table → MarketDataNotAvailableError
- 250 rows seeded → returns last 200 sorted asc
- tenant isolation: tenant A's INSERTs invisible to tenant B's read

**`apps/api/tests/unit/contexts/trading/market_data/test_ingestion_service.py`** (~6 tests)
- success path: ingestor returns success; audit row written `status=success`
- partial failure: ingestor returns 1 failure of 3; audit row `status=partial`
- full failure: ingestor raises; audit row `status=failed` + error captured
- rate-limit refused: 10 audit rows in last hour → MarketDataRateLimitedError raised + audit row `status=rate_limited`
- env-var override: `IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR=2` → 2nd call refused
- audit timing: `duration_ms > 0` for both success + failure paths

### 4.2 Migration roundtrip test (existing pattern)

`test_alembic_roundtrip.py` (existing) auto-discovers `0012_market_data_tables`; no new code needed if alembic detects it.

### 4.3 Integration test (1 critical test)

`tests/integration/test_trading_pipeline_e2e.py::test_propose_to_fill_chain` — the canonical end-to-end. Specified in §2.14.

### 4.4 CLI smoke tests (~2 tests)

`tests/unit/cli/test_market_data_cli.py`:
- `iguanatrader market-data --help` exits 0 + lists subcommands
- `iguanatrader market-data sync --symbols AAPL` invokes ingestion service with expected args (mocked)

## 5. Acceptance criteria

Code-level (verifiable by tests + CI):

1. `MarketDataPort` Protocol declared; 3 adapters compile + mypy --strict.
2. Migration `0012_market_data_tables.py` applies forward + backward.
3. `_make_strategy_resolver` returns an async closure that resolves a real `StrategyConfig` row (no NotImplementedError).
4. `bootstrap_routines` registers 5 routines; the propose-loop factory issues `trading_service.propose(...)` per (symbol, config) tuple.
5. `MarketDataIngestionService` rate-limits via the audit table; rate-limit error is observable in the audit row.
6. ≥18 tests across unit/integration; all pass in CI.
7. mypy --strict + ruff + black + pre-commit + CI all green.

Operator-driven (verified post-merge):

8. Paper-mode daemon boot → 06:00 UTC tick fires `market_data_sync` → bars appear in `market_data_bars` for watchlist symbols.
9. Subsequent midday tick fires propose loops → at least one proposal flows through the bus → broker fill recorded.
10. `iguanatrader market-data sync` CLI works end-to-end + respects rate limit.
11. `iguanatrader market-data backfill --symbol AAPL --days 365` works.

## 6. Cross-context interaction

- **Reads**: `tenant_id_var`, `session_var` ContextVars (slice 2 D2). DB reads from `strategy_configs` (existing), `market_data_bars` (new).
- **Writes**: `market_data_bars` UPSERT, `market_data_sync_audit` INSERT. Both via `MarketDataIngestionService`.
- **Bus emissions**: NONE from this slice's NEW code. Existing `TradingService.propose` continues to publish `ProposalCreated` per slice T1+T4 contract.
- **Migration**: `0012`. No collisions per migration-slot-reservation.md (latest: `0011`).
- **Imports**: lazy across daemon → market_data package boundary (gotcha #29). Direct imports only inside command/handler bodies.

## 7. Open questions resolved

1. **IBKR connection sharing**: SHARE the broker's `IbAsyncIBClient` with the ingestor. Cron schedule prevents temporal overlap (06:00 UTC ingestor vs 08:00+ UTC propose loops). Revisit if a contention bug appears.
2. **Default timeframe for v1**: HARDCODE `"1d"` everywhere; expose as env-var `IGUANATRADER_MARKET_DATA_DEFAULT_TIMEFRAME` with `"1d"` default for forward-compat. Donchian/SMA strategies in this repo are daily-bar; intraday is a v2 SaaS concern.
3. **`market_data_bars.tenant_id` NULL-ability**: KEEP NOT NULL for consistency with the rest of the schema and the slice-3 tenant_listener invariant. Storage cost is negligible at v1 tenant scale; revisit at v2 SaaS when tenant count > 30 with a migration to add a `(symbol, timeframe, ts)` shared-row pattern alongside.

## 8. Migration slot reservation

| Slot | File | Tables | Down-revision |
|---|---|---|---|
| `0012` | `0012_market_data_tables.py` | `market_data_bars`, `market_data_sync_audit` | `0011_orchestration_tables` |

No collision risk: latest existing slot is `0011`. Per [migration-slot-reservation.md](../../../.ai-playbook/specs/migration-slot-reservation.md).
