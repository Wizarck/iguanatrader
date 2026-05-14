# Retrospective: proposals-list-endpoint

- **PR**: [#149](https://github.com/Wizarck/iguanatrader/pull/149) (merged 2026-05-14, squash `a16395d`).
- **Archive path**: `openspec/changes/archive/2026-05-14-proposals-list-endpoint/`
- **Lines shipped**: 394 insertions / 29 deletions. CI 15/15 green on first push.

## What worked

- **"STOP after gh pr create" instruction** in the agent prompt saved ~10min of task budget — agent shipped end-to-end in 6m20s vs the ~16min PR #143 timeout pattern. Lock in for all future code-writing agent prompts.
- **Last 501 stub closed** — `STUB_ENDPOINTS = []` in `test_trading_route_stubs.py`. The parametrized test still exists (no-op on empty list); the OpenAPI smoke check stays. Clean state going into v1.5+.
- **`_stub` helper + `NotImplementedFeatureError` import removed** from `routes/proposals.py` once the only remaining caller went away. Linter-friendly + zero dead code.
- **Pattern mirrors `TradeRepository.list_for_tenant`** exactly — same shape, same pagination posture (`next_cursor=None` until v2). Zero invention.

## What didn't

- **FK constraint on `TradeProposal.strategy_config_id` required real seed** — the brief implied `strategy_config_id=uuid4()` would work like in `test_portfolio_routes.py`, but SQLite's `PRAGMA foreign_keys=ON` (wired in `persistence/session.py:45`) rejects bogus FK refs. Fix: agent seeded a real `StrategyConfig` row first. Pre-flag for future tests: when constructing standalone `TradeProposal` rows (no parent `Trade`), seed the referenced `StrategyConfig` first. `test_portfolio_routes` masks this because every proposal there is paired with a Trade insert in the same session.
- **httpx `cookies={...}` per-request deprecation warning escalated to test failure** — `pyproject.toml::filterwarnings = ["error"]` flips the warning to an error. Agent switched to `client.cookies.set(...)` (the canonical pattern from `test_trades_route_smoke.py`). Pre-flag: existing `test_strategies_routes.py` (from PR #142) likely has the same latent issue but outside this slice's scope. Follow-up: `chore-test-cookies-pattern-migration` could sweep all tests to the new pattern.

## Carry-forward

- **Pagination cursor on `/proposals`** — `next_cursor=None` in v1; v2 SaaS slice adds cursor when proposal volume warrants.
- **Filter params** (by symbol / date range / state) — v1.5 `proposals-filters` slice.
- **Manual proposal POST** — `ProposalIn` DTO planted but endpoint deferred to v2.
- **Frontend consumer** — no UI uses this list yet. Will be consumed by a future "Recent proposals" widget on the portfolio dashboard + the proposal-detail-view from the `/approvals` tab.
- **`test_strategies_routes.py` cookies-pattern migration** — flagged for follow-up sweep.

## Pattern usage

- **STOP after gh pr create in agent prompts** — saves task budget, parent handles CI monitoring. Lock into the agent-spawn template.
- **Cleanup the stub helper when its last caller leaves** — keeps the route file tight; ruff/mypy stay happy.
- **`STUB_ENDPOINTS = []` as the goal state** — parametrized test naturally no-ops; the existence of the test is documentation that "any future 501 stub MUST be added to this list".
- **`client.cookies.set` + plain `client.get/post` over `cookies={...}` kwarg** — canonical httpx pattern; survives `filterwarnings = ["error"]`.
