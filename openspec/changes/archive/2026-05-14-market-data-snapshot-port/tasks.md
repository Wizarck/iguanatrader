# Tasks: market-data-snapshot-port

- [ ] 1. `apps/api/src/iguanatrader/api/routes/portfolio.py` — add `_fetch_last_price(adapter, symbol) -> Decimal | None` (catches `MarketDataNotAvailableError` → returns `None`).
- [ ] 2. Same file — add `_compute_unrealized_pnl(*, trade, avg_entry, last_price) -> Decimal | None` (null-safe; sign-aware buy/sell).
- [ ] 3. Same file — update `_trade_to_position` signature to take `(trade, avg_entry_price, last_price, unrealized_pnl)`.
- [ ] 4. Same file — `list_positions` body: per-symbol `last_price_by_symbol` cache, fetch via `DBMarketDataAdapter`, compute unrealized per position. Extend `portfolio.positions.fetched` log with `symbols_with_market_data` int.
- [ ] 5. `apps/api/tests/integration/test_portfolio_routes.py` — 3 new test cases (with market data, without, mixed). Reuse existing `_seed_open_trade_with_fills` helper; add a small `_seed_market_data_bar` helper that inserts a single `MarketDataBar` row in the test session.
- [ ] 6. Local scoped lint: ruff + black + mypy --strict + pytest on touched files.
- [ ] 7. Push + open PR with §4.5 self-review.
- [ ] 8. STOP after `gh pr create` returns the PR URL. Parent monitors CI.
