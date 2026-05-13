# Proposal: portfolio-pnl-and-equity-series

> **Enrich `GET /portfolio` with backend-computed day P&L + add `GET /portfolio/equity/series` for the sparkline.** Backend computation chosen over frontend computation because money math on `Decimal`-as-string in JS loses precision + the same number must agree across web, Telegram, postmarket email, and future Slack/mobile (single source of truth).

## Why

`trading-routes-portfolio-strategies-bodies` (PR #142, 2026-05-13) wired the 7 portfolio + strategies route stubs. `GET /portfolio` now returns the real `PortfolioSummaryOut { equity, open_trades, open_orders }`. Two gaps remain before the dashboard tab (`portfolio-dashboard-mvp`) can render its overview card + sparkline:

1. **Day P&L is missing** from `PortfolioSummaryOut`. The frontend could derive it, but the calculation requires fetching yesterday's-close-or-today's-first snapshot, JS number-precision loss is unacceptable for money math, and the same number must match Telegram `/daily` + future postmarket email + Slack alerts. Single Python source of truth.
2. **Equity timeseries endpoint is missing.** Current `GET /portfolio/equity` returns one latest snapshot. The dashboard's sparkline needs ~30 days of points. `EquitySnapshotListOut` DTO was planted by T1 but no endpoint exposes it.

This slice closes both gaps in a single bundle (~3.5h) so the next UI slice (`portfolio-dashboard-mvp`, re-scoped against the real DTO shape) ships with no further backend gating.

## What

### DTO additions

`apps/api/src/iguanatrader/api/dtos/trades.py` — extend `PortfolioSummaryOut`:

```python
class PortfolioSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equity: EquitySnapshotOut
    open_trades: list[TradeOut]
    open_orders: list[OrderOut]
    # NEW (this slice):
    day_pnl_abs: Decimal | None = Field(
        default=None,
        examples=[Decimal("237.45")],
    )  # null when no baseline snapshot for today exists yet
    day_pnl_pct: Decimal | None = Field(
        default=None,
        examples=[Decimal("0.00237")],
    )  # fractional (0.00237 = 0.237%); frontend multiplies *100 for display
```

Both default to `None` so existing callers that don't yet set them still construct cleanly. `extra="forbid"` is preserved (the existing TypeScript regen will pick up the new fields).

### Day P&L computation

`apps/api/src/iguanatrader/api/routes/portfolio.py::get_portfolio` — add a third repo call + the computation:

```python
day_open: EquitySnapshot | None = await equity_repo.get_first_snapshot_today_for_tenant()
day_pnl_abs: Decimal | None = None
day_pnl_pct: Decimal | None = None
if latest_equity is not None and day_open is not None and day_open.account_equity > 0:
    day_pnl_abs = latest_equity.account_equity - day_open.account_equity
    day_pnl_pct = day_pnl_abs / day_open.account_equity
```

**"Today" semantics**: UTC midnight. The first snapshot with `created_at >= today_utc_midnight` is the baseline. This treats day_pnl as "since the daemon's first snapshot of today" — which for a 24/7 daemon equals "since yesterday's close" (snapshot written at 00:00:01 UTC after the listener loop ticks). If the daemon was down overnight, the baseline shifts to whenever it first ticked today — documented as a v1 quirk (the operator's mental model needs to allow for this; alternative would be "last snapshot of yesterday" but introduces an extra query + null-handling path).

**Multi-timezone is v1.5**: SaaS tenants in EU/Asia want their own day boundary. Defer.

### Equity timeseries endpoint

`apps/api/src/iguanatrader/api/routes/portfolio.py` — new endpoint:

```python
@router.get("/equity/series", response_model=EquitySnapshotListOut)
async def equity_series(
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EquitySnapshotListOut:
    """Return equity snapshots for the last `days` days (ordered ASC)."""
```

`EquitySnapshotListOut` already exists (`dtos/trades.py:168-175`). `days` default = 30 matches the sparkline's typical horizon; max=365 prevents tenants from accidentally pulling years of data. Returns `items: []` (NOT 404) when no snapshots fall in the window — the dashboard sparkline renders "Sin datos aún" inline.

### Repo additions

`apps/api/src/iguanatrader/contexts/trading/repository.py::EquitySnapshotRepository`:

- `get_first_snapshot_today_for_tenant() -> EquitySnapshot | None` — first snapshot where `created_at >= today_utc_midnight`, ordered ASC, limit 1.
- `list_for_tenant_window(days: int) -> list[EquitySnapshot]` — all snapshots where `created_at >= now - days*24h`, ordered `created_at ASC` (chronological — matches sparkline expectation).

Tenant filter automatic via slice-3 `tenant_listener`. Both methods follow the same pattern as the existing `get_latest_for_tenant`.

### Tests

**`apps/api/tests/integration/test_portfolio_routes.py`** (extend the existing β file from PR #142):

1. `test_get_portfolio_day_pnl_null_when_no_today_snapshot` — empty tenant + a single snapshot timestamped yesterday → `day_pnl_abs is None`, `day_pnl_pct is None`.
2. `test_get_portfolio_day_pnl_computed_with_baseline` — seed two snapshots (today 09:00 UTC at 100k + today 14:00 UTC at 102.5k) → response `day_pnl_abs == "2500"`, `day_pnl_pct == "0.025"`.
3. `test_get_portfolio_day_pnl_negative` — baseline 100k → current 99k → `day_pnl_abs == "-1000"`, `day_pnl_pct == "-0.01"`.
4. `test_get_equity_series_empty_returns_empty_items` — no snapshots → 200 + `{"items": [], "total": 0, "next_cursor": null}`.
5. `test_get_equity_series_returns_only_in_window` — seed snapshots at -5d, -15d, -45d → `?days=30` returns 2 (the -5d + -15d), in chronological order.
6. `test_get_equity_series_clamps_days_param` — `?days=0` → 422 validation error; `?days=400` → 422.
7. `test_equity_series_isolated_across_tenants` — tenant A has snapshots in window, tenant B sees `items: []`.

7 new test cases. Each `<10 lines` thanks to the existing seed helpers + `client` fixture.

### Logs

- `portfolio.summary.fetched` — extend with `day_pnl_computed: bool` field.
- `portfolio.equity_series.fetched` — new event with `tenant_id`, `days`, `count`.

## Out of scope

- **Multi-timezone day boundary** — v1 uses UTC midnight. SaaS tenants in EU/Asia want their own day = v1.5 follow-up (`portfolio-day-boundary-tenant-tz`).
- **Yesterday's-close baseline** — v1 uses first-snapshot-today. If the daemon was down overnight the baseline shifts to whenever it first ticked today (documented v1 quirk). True "yesterday close" requires querying `MAX(created_at) WHERE created_at < today_utc_midnight` — adds a second query + null branch for first-ever-day. Defer.
- **Equity series cursor pagination** — `EquitySnapshotListOut.next_cursor` stays `null` in v1 (max 365 days × N-per-day fits in one response).
- **Sparkline rendering** — frontend slice (`portfolio-dashboard-mvp` re-scoped) consumes this endpoint.
- **Cash-only / instrument-bucket breakdown** — future endpoint when the dashboard adds an allocation pie chart.
- **`PortfolioSummaryOut` enrichment beyond day P&L** — `total_value` / `cash_balance` / `position_count` are NOT added; frontend reads them 1:1 from `equity.account_equity` / `equity.cash_balance` / `len(open_trades)` (no money math; no precision risk).
