# Proposal: trading-routes-portfolio-strategies-bodies

> **Wire the 7 portfolio + strategies route stubs that T4 left as 501.** The catalogue claimed T4 (`trading-routes-and-daemon`) shipped these bodies; reality (verified 2026-05-13) is they still raise `NotImplementedFeatureError`. This slice fills them so the upcoming dashboard UI slices (`portfolio-dashboard-mvp`, `strategies-config-ui`) have real backends to consume.

## Why

While drafting `portfolio-dashboard-mvp` an audit revealed:

- `apps/api/src/iguanatrader/api/routes/portfolio.py:37-58` — all 3 endpoints raise `_stub(...)` → 501.
- `apps/api/src/iguanatrader/api/routes/strategies.py:38-72` — all 4 endpoints raise `_stub(...)` → 501.
- `apps/api/tests/integration/test_trading_route_stubs.py:40-42` pins this 501 contract — must be rewritten.

The DTOs (`PortfolioSummaryOut`, `StrategyConfigOut`, `EquitySnapshotOut`) and the repos (`TradeRepository`, `OrderRepository`, `EquitySnapshotRepository`, `StrategyConfigRepository`) were planted by T1 + T4-followup. What's missing is the route bodies + a few repo query methods + the missing `PositionOut` DTO.

This is a backend-only slice. No UI. Two follow-on UI slices (`portfolio-dashboard-mvp` already drafted but blocked; `strategies-config-ui` separate) consume the result.

## What

### Route bodies — portfolio

**`apps/api/src/iguanatrader/api/routes/portfolio.py`** — replace `raise _stub(...)` with real bodies:

- **`GET /api/v1/portfolio`** → `PortfolioSummaryOut`:
  - `equity` = latest `EquitySnapshot` for tenant (or a synthesised zero-snapshot if none yet, with `account_equity=0, cash_balance=0, snapshot_kind="empty"`).
  - `open_trades` = `Trade` rows where `state == "open"`, ordered `opened_at DESC`.
  - `open_orders` = `Order` rows where `state in {"new", "submitted", "partially_filled"}`, ordered `created_at DESC`.

- **`GET /api/v1/portfolio/positions`** → `PositionListOut { items: list[PositionOut] }` (NEW DTOs). A "position" is derived from open trades + their cumulative fills:
  - For each `Trade` with `state == "open"`:
    - `symbol = trade.symbol`
    - `side = trade.side`
    - `quantity = trade.quantity` (signed by side at the caller's convenience, kept unsigned in DTO and side carried separately)
    - `avg_entry_price = sum(fills.fill_price × fills.quantity_filled) / sum(fills.quantity_filled)`, or `None` if no fills yet.
    - `last_price = None` for now (market-data hook is a follow-up slice; comment `# TODO market-data-snapshot follow-up`). Frontend renders "—" when null.
    - `unrealized_pnl = None` (depends on `last_price`; null for now).
    - `opened_at = trade.opened_at`
  - Sorted by `opened_at DESC`. Empty list when no open trades.

- **`GET /api/v1/portfolio/equity`** → `EquitySnapshotOut` (single, latest). 404 if tenant has zero snapshots — call this out in the route docstring + return `NotFoundError`. (Alternative considered: return a synthesised zero snapshot like `/portfolio` does; rejected because callers of `/equity` specifically want history. Frontend handles 404 by rendering "Sin snapshots aún" inline.)

### Route bodies — strategies

**`apps/api/src/iguanatrader/api/routes/strategies.py`** — replace `raise _stub(...)`:

- **`GET /api/v1/strategies`** → `StrategyConfigListOut`: all `StrategyConfig` rows for tenant, ordered `(symbol ASC, strategy_kind ASC)`.
- **`GET /api/v1/strategies/{symbol}`** → `StrategyConfigOut`: the first (oldest-`created_at`) enabled config matching `symbol`, or 404 if none. Backend DB supports multiple kinds per symbol but the v1 UI assumes one — document this ambiguity in the route docstring. Multi-kind support is a v1.5 slice (`strategies-multi-kind-ui`).
- **`PUT /api/v1/strategies/{symbol}`** → `StrategyConfigOut`: delegates to `StrategyConfigRepository.upsert(symbol=symbol, ...)`. Existing repo method.
- **`DELETE /api/v1/strategies/{symbol}`** → `{"status": "disabled", "symbol": ...}`: sets `enabled=False` on all configs for that symbol (soft delete; no DB row removal — preserves audit history). 404 if symbol has no rows.

### Repo additions

**`apps/api/src/iguanatrader/contexts/trading/repository.py`**:

- `TradeRepository.list_open_for_tenant()` — `state == "open"`, ordered `opened_at DESC`.
- `OrderRepository.list_open_for_tenant()` — `state in {"new", "submitted", "partially_filled"}`, ordered `created_at DESC`.
- `EquitySnapshotRepository.get_latest_for_tenant()` — `order_by(created_at DESC).limit(1)`.
- `FillRepository.list_for_trade_chronological()` — already exists as `list_for_trade` (sorted ASC).
- `StrategyConfigRepository.list_for_tenant()` — all rows ordered `(symbol, strategy_kind)`.
- `StrategyConfigRepository.get_first_enabled_by_symbol(symbol)` — first enabled by `created_at ASC`.
- `StrategyConfigRepository.disable_all_by_symbol(symbol)` — `UPDATE ... SET enabled=False WHERE symbol=?`, returns affected row count.

Tenant filtering remains automatic via the slice-3 `tenant_listener`.

### DTOs

**`apps/api/src/iguanatrader/api/dtos/trades.py`** — add:

```python
class PositionOut(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=False)
    trade_id: UUID
    symbol: str
    side: str  # "buy" | "sell"
    quantity: Decimal
    avg_entry_price: Decimal | None  # null when no fills yet
    last_price: Decimal | None  # always null in v1 (market-data follow-up)
    unrealized_pnl: Decimal | None  # always null in v1
    opened_at: datetime

class PositionListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[PositionOut]
    total: int | None = None
```

Both exported via `__all__`.

### Tests

- **`apps/api/tests/integration/test_trading_route_stubs.py`** — DELETE the assertions that pin 501 on `/portfolio*` and `/strategies*`. Leave the file for any remaining (genuinely unimplemented) stubs.
- **`apps/api/tests/integration/test_portfolio_routes.py`** (NEW):
  1. `GET /portfolio` empty tenant → synthesised empty equity + `open_trades=[]` + `open_orders=[]`.
  2. `GET /portfolio` with seeded data → echoes back.
  3. `GET /portfolio/positions` no open trades → `items=[]`.
  4. `GET /portfolio/positions` with 2 open trades + fills → 2 items with computed `avg_entry_price`.
  5. `GET /portfolio/positions` open trade with no fills yet → `avg_entry_price=null`, `last_price=null`.
  6. `GET /portfolio/equity` no snapshots → 404 `NotFoundError`.
  7. `GET /portfolio/equity` with snapshot → echoes latest.
  8. Cross-tenant isolation: tenant A's data invisible to tenant B (via `tenant_listener`).

- **`apps/api/tests/integration/test_strategies_routes.py`** (NEW):
  1. `GET /strategies` empty tenant → `items=[]`.
  2. `GET /strategies` with 2 configs → both rows.
  3. `GET /strategies/{symbol}` no config → 404.
  4. `GET /strategies/{symbol}` with single enabled config → row.
  5. `GET /strategies/{symbol}` with two kinds → first (oldest) returned (doc'd ambiguity).
  6. `PUT /strategies/{symbol}` create → 200 + row persisted; `PUT` again → version bumps.
  7. `DELETE /strategies/{symbol}` existing → all rows `enabled=False`; row still in DB.
  8. `DELETE /strategies/{symbol}` missing → 404.
  9. Cross-tenant isolation.

### Logs

Replace `trading.routes.stub_invoked` log call sites with topical events: `portfolio.summary.fetched`, `portfolio.positions.fetched`, `portfolio.equity.fetched`, `strategies.list.fetched`, `strategies.upsert.applied`, `strategies.disabled`.

## Out of scope

- **Market-data integration** for `last_price` + `unrealized_pnl` on `PositionOut` — both stay null in v1; the follow-up slice (`market-data-snapshot-port`) wires this.
- **Multi-kind-per-symbol UI** for strategies — backend allows it (composite UNIQUE is `(tenant_id, strategy_kind, symbol)`), but v1 GET-by-symbol/DELETE-by-symbol assume single-kind. `strategies-multi-kind-ui` lands later.
- **Equity timeseries endpoint** — `GET /portfolio/equity` returns the latest single snapshot; a `GET /portfolio/equity/series?days=N` lands in `equity-timeseries-endpoint` (separate, ahead of `portfolio-dashboard-mvp` resume since the dashboard wants a sparkline).
- **Frontend wiring** — this slice is pure backend. `portfolio-dashboard-mvp` + `strategies-config-ui` consume the result.
- **Hard delete of strategies** — out of scope; soft-disable preserves audit log.
