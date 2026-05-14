# Retrospective: trading-routes-portfolio-strategies-bodies

- **PR**: [#142](https://github.com/Wizarck/iguanatrader/pull/142) (merged 2026-05-13, squash `2505089`).
- **Archive path**: `openspec/changes/archive/2026-05-13-trading-routes-portfolio-strategies-bodies/`
- **Lines shipped**: 1427 insertions / 79 deletions across 9 files. CI 15/15 green after 1 fix round (`black --check` flagged `repository.py` — local Windows run had only spot-checked the test files).

## What worked

- **Audit-driven slice scope** — the original `portfolio-dashboard-mvp` proposal assumed the backend was shipped. Spawning an agent for that slice surfaced the false premise; the parent agent stopped the run, audited all 7 dashboard backends, and re-scoped this slice to fill exactly the gap. Two parallel slices (this one + [[trades-list-and-detail]]) replaced the original blocked plan. Pre-pattern for future catalogue-vs-reality drift: AUDIT FIRST, slice second.
- **`PositionOut` + `PositionListOut` DTOs as the unblocking artefact** — the missing piece the portfolio-mvp attempt discovered. `PositionOut.last_price` + `unrealized_pnl` are explicitly null in v1 (market-data hook is a follow-up); the frontend renders `—` for nulls. Honest typing + a clear deferred-work boundary in one DTO.
- **Synthesised-empty equity vs 404 split** — `GET /portfolio` for an empty tenant returns a zero `EquitySnapshotOut` with `snapshot_kind="empty"` (sentinel; not persisted; not in the DB CHECK constraint enum), so the dashboard renders "Sin movimiento aún" without special-casing. `GET /portfolio/equity` keeps the 404 contract because callers of `/equity` specifically want history-or-nothing. Two endpoints, two distinct semantics, both documented in their docstrings.
- **DELETE `/strategies/{symbol}` as per-row UPDATE through ORM** (NOT bulk `update().where()`) — the slice-3 `tenant_listener` filters the preceding SELECT, then the `before_update` hook bumps `version` per row. Bulk UPDATE would bypass both. Soft-disable preserves the append-only audit log.
- **Tests structured per route group** — `test_portfolio_routes.py` (8 cases) + `test_strategies_routes.py` (9 cases) + the stub-pinning test updated to keep coverage on the one remaining genuine stub (`GET /proposals`). Mirrors the existing `test_trade_routes.py` shape — easy to extend when the next backend gap closes.
- **Repo additions follow the BaseRepository tenant-listener pattern** — none of the new query methods need explicit `where(tenant_id=...)`; the slice-3 listener handles it automatically on every SELECT bound to `session_var`.

## What didn't

- **Local `black --check` skipped on `repository.py`** — I ran black + ruff + mypy on the new test files only, not on every modified module. CI's `black --check .` flagged a reformat-needed on `repository.py` + the `Pre-commit hooks` job rejected the commit. Cost: one quick fix-and-push round (~3min CI cycle re-run). Pre-flag: when modifying a file, run `poetry run black --check <file>` BEFORE commit OR run `poetry run black apps/api/` once over the whole tree. Don't trust spot-checks.
- **β agent's stub-test fix included `GET /proposals/{id}`** as a remaining stub — but that endpoint was actually wired by an earlier slice (returns 404 on miss, not 501). Caught locally via `pytest test_trading_route_stubs.py` before push. Pre-flag: when reviewing remaining stubs, audit each one with a real GET — don't assume from the route file's `_stub` import.
- **OpenAPI typegen** — CI's `Regenerate packages/shared-types from /openapi.json` job ran cleanly + the regenerated types were committed. Worth noting: the typegen IS scripted (not manual) and the slice-5 dynamic-discovery picks up the new `PositionOut` / `PositionListOut` shapes without any `routes/__init__.py` edit.

## Carry-forward

- **Market-data hook for `PositionOut.last_price` + `unrealized_pnl`** — both null in v1. Follow-up slice `market-data-snapshot-port` wires the values from a price-snapshot port (IBKR or sidecar).
- **`GET /portfolio/equity/series?days=N`** — the new `/portfolio/equity` endpoint returns the latest single snapshot. A series endpoint is needed for the dashboard sparkline (see [[portfolio-dashboard-mvp]] proposal §What). Owned by `equity-timeseries-endpoint`.
- **Multi-kind-per-symbol UI for strategies** — backend allows multi-kind (composite UNIQUE is `(tenant_id, strategy_kind, symbol)`); v1 GET-by-symbol picks oldest enabled. `strategies-multi-kind-ui` is v1.5.
- **Hard delete of strategies** — currently soft-disable via `enabled=False`. Hard-delete would need a separate audit-event so the append-only contract holds. Defer until a real operator asks.
- **Unblocks** — `portfolio-dashboard-mvp` (proposal exists in `openspec/changes/`, blocked-note + stale DTO refs to be updated when resumed) + `strategies-config-ui` (future slice).

## Pattern usage

- **Audit before slice** — when a proposal's premise rests on "X is already shipped per the catalogue", verify via grep before scoping. Saved this session ~30min once the false premise surfaced (vs spending it building UI against a 501 backend).
- **Synthesised-empty DTO sentinel** — `snapshot_kind="empty"` is a DTO-only value (not persisted, not in DB enum). Pattern: when a "first-boot empty" shape would be useful, synthesise a zero DTO + use a string sentinel field that the frontend can switch on without 404-handling logic.
- **Per-row UPDATE for soft-delete** — `for row in select(...).where(symbol=...): row.enabled = False`. Listener-friendly + version-bump-friendly. Bulk UPDATE bypasses both; never use for tenant-scoped or audited tables.
- **Stub-pinning test that shrinks as bodies land** — `STUB_ENDPOINTS` list contracts to only-genuinely-unwired endpoints + the test parametrizes over the list. Easy to maintain; trivially verifiable each slice closes its endpoints.
