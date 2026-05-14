# Tasks: portfolio-pnl-and-equity-series

- [ ] 1. `apps/api/src/iguanatrader/api/dtos/trades.py` — extend `PortfolioSummaryOut` with `day_pnl_abs: Decimal | None = None` + `day_pnl_pct: Decimal | None = None` (both with `Field(default=None, examples=[...])`); keep `extra="forbid"`.
- [ ] 2. `apps/api/src/iguanatrader/contexts/trading/repository.py::EquitySnapshotRepository` — add `get_first_snapshot_today_for_tenant() -> EquitySnapshot | None` (first row where `created_at >= today_utc_midnight`, ASC, limit 1).
- [ ] 3. Same repo — add `list_for_tenant_window(days: int) -> list[EquitySnapshot]` (all rows where `created_at >= now - days*24h`, ordered `created_at ASC`).
- [ ] 4. `apps/api/src/iguanatrader/api/routes/portfolio.py::get_portfolio` — fetch `day_open` via the new repo method + compute `day_pnl_abs`/`day_pnl_pct` (guard: `latest_equity != None and day_open != None and day_open.account_equity > 0`); pass both to `PortfolioSummaryOut`. Update the `portfolio.summary.fetched` log line with `day_pnl_computed: bool`.
- [ ] 5. `apps/api/src/iguanatrader/api/routes/portfolio.py` — new `GET /equity/series` endpoint, `days: int = Query(default=30, ge=1, le=365)`, returns `EquitySnapshotListOut`. Log `portfolio.equity_series.fetched` with `tenant_id`, `days`, `count`.
- [ ] 6. `apps/api/tests/integration/test_portfolio_routes.py` — extend with 7 new test cases per proposal §Tests (day_pnl null/positive/negative + series empty/windowed/clamp/cross-tenant).
- [ ] 7. ruff + black --check + mypy --strict green locally on every modified/new file.
- [ ] 8. pytest green locally for `tests/integration/test_portfolio_routes.py` (existing 8 + new 7 = 15 cases).
- [ ] 9. Push + open PR with §4.5 self-review checklist pre-populated.
- [ ] 10. Wait for CI all-green (15 checks).
