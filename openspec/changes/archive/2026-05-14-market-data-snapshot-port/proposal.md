# Proposal: market-data-snapshot-port

> **Populate `PositionOut.last_price` + `PositionOut.unrealized_pnl` in `GET /api/v1/portfolio/positions`** using the existing `DBMarketDataAdapter` to fetch each open position's symbol last-bar close. Both fields ship `null` today (per [[trading-routes-portfolio-strategies-bodies]] retro — explicitly deferred to this slice). Last user-facing v1 gap closed.

## Why

`PositionOut.last_price` and `PositionOut.unrealized_pnl` were typed `Decimal | None` in PR #142 with the explicit deferral: "the market-data hook is a follow-up slice". The frontend already renders "—" when null (PR #144), so this slice ships a backend-only enrichment with zero UI change required.

The infrastructure is in place:
- `DBMarketDataAdapter` (`contexts/trading/market_data/db.py`) queries `market_data_bars` for the latest bar(s).
- `market_data_bars` table is populated by the `market_data_sync` cron routine + the `iguanatrader market-data backfill` CLI (both already shipped).

What's missing: the `list_positions` route doesn't yet consult the port. This slice wires it.

## What

### Route enrichment

`apps/api/src/iguanatrader/api/routes/portfolio.py::list_positions` — per-symbol cache + per-position enrichment:

```python
# After computing open_trades:
md_adapter = DBMarketDataAdapter()
last_price_by_symbol: dict[str, Decimal | None] = {}

for trade in open_trades:
    if trade.symbol not in last_price_by_symbol:
        last_price_by_symbol[trade.symbol] = await _fetch_last_price(md_adapter, trade.symbol)

# Per-position enrichment:
positions: list[PositionOut] = []
for trade in open_trades:
    avg = await _compute_avg_entry_price(fill_repo, trade.id)
    last_price = last_price_by_symbol[trade.symbol]
    unrealized = _compute_unrealized_pnl(trade=trade, avg_entry=avg, last_price=last_price)
    positions.append(_trade_to_position(trade, avg, last_price, unrealized))
```

### Helpers (in `routes/portfolio.py` module)

```python
async def _fetch_last_price(
    adapter: DBMarketDataAdapter,
    symbol: str,
) -> Decimal | None:
    """Return last 1d-bar close for ``symbol``, or ``None`` if no bars exist."""
    try:
        bars = await adapter.get_bars(symbol=symbol, timeframe="1d", lookback_bars=1)
    except MarketDataNotAvailableError:
        return None
    if not bars.bars:
        return None
    return Decimal(bars.bars[-1].close)


def _compute_unrealized_pnl(
    *,
    trade: Trade,
    avg_entry: Decimal | None,
    last_price: Decimal | None,
) -> Decimal | None:
    """Compute mark-to-market unrealized P&L for an open trade.

    Returns ``None`` when either ``avg_entry`` or ``last_price`` is missing
    (frontend renders "—" for the position row). Sign convention:
    ``buy`` side → ``(last - entry) * qty``; ``sell`` side → ``(entry - last) * qty``.
    """
    if avg_entry is None or last_price is None:
        return None
    delta = last_price - avg_entry if trade.side == "buy" else avg_entry - last_price
    return delta * Decimal(trade.quantity)
```

### `_trade_to_position` signature update

Currently takes `(trade, avg_entry_price)`. New signature: `(trade, avg_entry_price, last_price, unrealized_pnl)`. All three Decimal-or-None pass through to the DTO.

### Logs

Extend `portfolio.positions.fetched` with `symbols_with_market_data: int` (count of unique symbols where `last_price_by_symbol[symbol] is not None`). Operators can grep this to detect "stale market data" silently degrading the dashboard.

### Tests

`apps/api/tests/integration/test_portfolio_routes.py` — 3 new cases:

1. `test_get_positions_with_market_data_computes_last_price_and_unrealized_pnl`:
   - Seed open trade (BUY 10 @ avg 100) + seed 1 daily bar @ close 110 for that symbol.
   - Expect `last_price == "110"`, `unrealized_pnl == "100"` (= (110-100) × 10).

2. `test_get_positions_without_market_data_leaves_last_price_null`:
   - Seed open trade but NO market data bars for the symbol.
   - Expect `last_price is None`, `unrealized_pnl is None`.

3. `test_get_positions_mixed_market_data`:
   - Seed 2 open trades on different symbols; bars exist for symbol A but not B.
   - Expect A's row populated; B's row null.
   - Expect log shows `symbols_with_market_data: 1`.

Plus update the existing `test_get_positions_with_fills_computes_weighted_avg_entry_price` + `test_get_positions_open_trade_with_no_fills_yields_null_avg_entry` assertions to reflect that `last_price` may now be populated if test seeds bars (they currently expect null — keep them seeding NO bars so the assertions hold).

### Helper extraction

`_fetch_last_price` + `_compute_unrealized_pnl` go in `routes/portfolio.py` as module-private helpers (single caller; no need to hoist to a shared module yet). If a 2nd caller appears (e.g., a future "unrealized P&L for closed-trade-since-fill" computation), extract then.

## Out of scope

- **Intraday last-price freshness** — uses 1d-bars; intraday updates would need a 1m-bar fallback chain or a live broker quote. v1.5 (`market-data-intraday-snapshot`).
- **Mark-to-market currency conversion** — assumes `trade.symbol` quote currency matches the position's reported currency. v1.5 when multi-currency lands.
- **Equity update propagation** — `EquitySnapshot.unrealized_pnl` (column on the snapshot table) is NOT updated by this slice; that's the daemon's responsibility. This slice only enriches the read-only `/portfolio/positions` route.
- **Frontend changes** — none. UI already handles null gracefully via "—" rendering (PR #144).
- **Sell-side short positions** — `side == "sell"` is supported in the unrealized-pnl formula but the v1 daemon typically only opens long positions. Test case for sell side is v1.5 when shorting is exercised.
