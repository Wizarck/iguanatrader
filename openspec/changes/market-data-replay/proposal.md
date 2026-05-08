# Proposal: market-data-replay

> CLI subcommand `iguanatrader market-data replay --routine=<name> --date=<YYYY-MM-DD>` to re-evaluate strategies against historical bars stored in `market_data_bars` (T4-followup-market-data). Read-only; no broker calls; no bus emissions.

## Why

T4-followup-market-data shipped the `market_data_bars` table and the daily `market_data_sync` ingestor (PR #105, archived 2026-05-08). The schema captures every historical bar fetched from IBKR per `(tenant, symbol, timeframe, ts)`. With ~200 days of daily bars per watchlist symbol, the operator can already inspect the data via SQL — but cannot easily ask: **"what would the midday routine on 2026-04-15 have proposed for AAPL given the bars-state-as-of-2026-04-15-13:00-UTC?"**.

This slice closes that gap with a CLI that:

1. Loads strategy_configs for the watchlist (current tenant).
2. For each (symbol, config) pair, loads the bars from `market_data_bars` ending at the target date+timeframe.
3. Calls `strategy.evaluate(symbol, bars, snapshot)` **directly** (no `TradingService.propose` — replay must NOT emit `ProposalCreated`, persist to `trade_proposals`, or touch the broker).
4. Prints a compact table: `(symbol, strategy_kind, would_propose: bool, side, quantity, entry_price, stop_price, why)`.

Use cases:

- **Postmortem ops**: "on 2026-04-15 the midday routine fired no proposals — why?". Replay shows the strategy returned `None` (no signal) for each symbol.
- **Pre-flight before flag flips**: operator changes `risk_pct` on a Donchian config; replays the last week to see how the new config would have proposed.
- **Backtest-lite**: not a full Lean-style backtest (no slippage, no commission, no equity curve), but enough to sanity-check strategy behaviour on real historical data.

## What

Single new CLI command + thin replay service. Pure additive on `cli/market_data.py` (already a Typer app from T4-followup-market-data).

### `iguanatrader market-data replay`

```
iguanatrader market-data replay
  --routine=<premarket|midday|postmarket|weekly_review>
  --date=<YYYY-MM-DD>
  [--symbols=AAPL,MSFT]
  [--timeframe=1d]
  [--lookback-bars=200]
  [--tenant=<slug>]
```

Calls `MarketDataReplayService.replay(...)`. Prints a table to stdout. Exits 0 on success (regardless of how many proposals fired); exits 2 on input validation errors (bad date format, unknown routine, no bars in DB).

### `MarketDataReplayService` (`apps/api/src/iguanatrader/contexts/trading/market_data/replay.py` NEW)

```python
@dataclass(frozen=True, slots=True)
class ReplayRow:
    symbol: str
    strategy_kind: str
    strategy_version: int
    would_propose: bool
    side: str | None  # "buy"/"sell"/None
    quantity: Decimal | None
    entry_price: Decimal | None
    stop_price: Decimal | None
    rationale: str  # "<no signal>" or strategy.evaluate's `why`-equivalent

@dataclass(frozen=True, slots=True)
class ReplayResult:
    routine: str
    as_of: datetime
    rows: list[ReplayRow]
    bars_loaded: int

class MarketDataReplayService:
    def __init__(
        self, *,
        market_data_port: MarketDataPort,
        strategy_config_repo: StrategyConfigRepository,
        strategy_resolver: Callable[[UUID], Awaitable[StrategyPort]],
    ) -> None: ...

    async def replay(
        self, *,
        symbols: list[str],
        routine: str,
        as_of: datetime,
        timeframe: str = "1d",
        lookback_bars: int = 200,
    ) -> ReplayResult: ...
```

Load path:

- For each symbol: `strategy_config_repo.list_enabled_for_symbol(symbol)`.
- For each config: `await market_data_port.get_bars(symbol=..., timeframe=..., lookback_bars=lookback_bars)`. **The adapter must support filtering by `as_of`** — see implementation note below.
- For each (symbol, config, bars): construct `StrategyConfigSnapshot`; call `await strategy_resolver(config.id)` to get strategy; call `strategy.evaluate(symbol, bars, snapshot)`.
- If proposal returned: build `ReplayRow(would_propose=True, ...)`. If `None`: `ReplayRow(would_propose=False, rationale="<no signal>")`.

### `DBMarketDataAdapter` `as_of` filter

Currently `DBMarketDataAdapter.get_bars(symbol, timeframe, lookback_bars)` returns the latest `lookback_bars` rows. For replay we need bars where `ts <= as_of`. Two options:

- (a) **Add `as_of: datetime | None = None` kwarg** to `MarketDataPort.get_bars`. Replay passes a non-None value; existing daemon callers leave None (preserve current behavior).
- (b) Expose a second method `get_bars_as_of(symbol, timeframe, lookback_bars, as_of)` on the Port.

(a) is more compact + idiomatic. Replay slice adds the optional kwarg to:
- `MarketDataPort.get_bars` Protocol.
- `InMemoryMarketDataAdapter.get_bars` (filter the seed list by ts ≤ as_of).
- `DBMarketDataAdapter.get_bars` (`AND ts <= :as_of` predicate).

`as_of=None` = current behavior (backwards-compatible). Existing T4-followup-market-data daemon callers leave it None.

## Out of scope

- **Slippage / commission / equity curve simulation**: this is replay-lite, not a full backtest. A future `backtest-engine` slice could build on top.
- **Multi-day replay loops** (`--start-date / --end-date`): v1 is single-as_of-tick. Operator scripts the date loop in shell if needed.
- **Replay against IB live (no DB hit)**: defeats the purpose; live IB is for production tick.
- **Persist replay results**: prints to stdout, not stored. v2 SaaS slice can persist if ops dashboards need a history.

## Acceptance criteria

1. `iguanatrader market-data replay --routine=midday --date=2026-04-15 --symbols=AAPL` runs end-to-end against a seeded sqlite DB.
2. Output table includes one row per (symbol, enabled-config) pair.
3. `would_propose=True` rows show side/quantity/entry/stop populated.
4. `would_propose=False` rows show empty + rationale `<no signal>`.
5. `MarketDataPort.get_bars` accepts optional `as_of: datetime | None = None`; `as_of=None` returns current behavior bit-identical (pre-replay slice).
6. mypy --strict + ruff + black + pre-commit + CI green.
7. ≥4 unit tests covering: replay with signal, replay without signal, replay rejects bad date format, replay handles symbol with no enabled configs.

## Blast radius

Additive only:

- `MarketDataPort.get_bars` Protocol gains optional kwarg (backwards-compat).
- 2 adapters (`InMemoryMarketDataAdapter`, `DBMarketDataAdapter`) gain the filter.
- 1 NEW `MarketDataReplayService` + 1 NEW CLI subcommand body.
- 1 NEW test file.

T4-followup-market-data archive surface untouched.

## Estimated effort

~3-4h, ~400 LoC (~150 src + ~200 tests + ~50 retro/openspec).
