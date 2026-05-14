# Tasks: proposals-list-endpoint

- [ ] 1. `apps/api/src/iguanatrader/contexts/trading/repository.py::TradeProposalRepository` — add `list_for_tenant() -> list[TradeProposal]` (order by `created_at DESC`).
- [ ] 2. `apps/api/src/iguanatrader/api/routes/proposals.py::list_proposals` — replace `raise _stub(...)` with real body using `TradeProposalRepository.list_for_tenant()`. Update log to `api.proposals.list` with `tenant_id` + `count`.
- [ ] 3. `apps/api/tests/integration/test_trading_route_stubs.py` — empty `STUB_ENDPOINTS = []` (parametrized test becomes a no-op; OpenAPI smoke check stays).
- [ ] 4. `apps/api/tests/integration/test_proposals_routes.py` (NEW) — 3 cases (empty / seeded sorted DESC / cross-tenant isolation).
- [ ] 5. Scoped ruff + black + mypy --strict + pytest green on touched files only.
- [ ] 6. Push + open PR with §4.5 self-review.
- [ ] 7. Wait CI all-green (15 checks).
