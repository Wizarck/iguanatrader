# Tasks: trading-routes-portfolio-strategies-bodies

- [ ] 1. `apps/api/src/iguanatrader/api/dtos/trades.py` — add `PositionOut` + `PositionListOut` (export via `__all__`)
- [ ] 2. `apps/api/src/iguanatrader/contexts/trading/repository.py` — add `TradeRepository.list_open_for_tenant`, `OrderRepository.list_open_for_tenant`, `EquitySnapshotRepository.get_latest_for_tenant`, `StrategyConfigRepository.list_for_tenant`, `StrategyConfigRepository.get_first_enabled_by_symbol`, `StrategyConfigRepository.disable_all_by_symbol`
- [ ] 3. `apps/api/src/iguanatrader/api/routes/portfolio.py` — wire 3 bodies: `GET /portfolio` (PortfolioSummaryOut), `GET /portfolio/positions` (PositionListOut), `GET /portfolio/equity` (single EquitySnapshotOut or 404). Replace `_stub` helper invocations; remove obsolete imports.
- [ ] 4. `apps/api/src/iguanatrader/api/routes/strategies.py` — wire 4 bodies: GET list, GET-by-symbol, PUT upsert, DELETE soft-disable.
- [ ] 5. `apps/api/tests/integration/test_trading_route_stubs.py` — DELETE 501 assertions for `/portfolio*` + `/strategies*`; keep file for any remaining genuine stubs.
- [ ] 6. `apps/api/tests/integration/test_portfolio_routes.py` (NEW) — 8 cases per proposal §Tests.
- [ ] 7. `apps/api/tests/integration/test_strategies_routes.py` (NEW) — 9 cases per proposal §Tests.
- [ ] 8. Logs: replace `trading.routes.stub_invoked` calls with topical events (per proposal §Logs).
- [ ] 9. Verify slice-5 OpenAPI typegen pipeline regenerates `packages/shared-types/src/index.ts` cleanly (run `pnpm openapi:gen` from repo root if scripted; otherwise manual).
- [ ] 10. ruff + black + mypy --strict + pytest green locally.
- [ ] 11. svelte-check + pnpm test green locally (regenerated TS types must not break web build).
- [ ] 12. Push + open PR with §4.5 pre-populated.
- [ ] 13. Wait for CI all-green.
