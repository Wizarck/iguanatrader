# Retrospective: trades-list-and-detail

- **PR**: [#141](https://github.com/Wizarck/iguanatrader/pull/141) (merged 2026-05-13, squash `741b837`).
- **Archive path**: `openspec/changes/archive/2026-05-13-trades-list-and-detail/`
- **Lines shipped**: 1297 insertions / 9 deletions across 17 files. CI 14/14 green on first push.

## What worked

- **Picking `/trades` over `/portfolio` after the audit**: drafting the `portfolio-dashboard-mvp` proposal exposed that `/api/v1/portfolio*` was still 501 stubs from T1 despite the catalogue's T4 entry claiming otherwise. Pivoting to `/trades` (verified-real backend per `trades-read-endpoints`, PR #112) let the UI shipment land same-day while the backend gap was being closed in parallel ([[trading-routes-portfolio-strategies-bodies]]).
- **Three reusable components hoisted now (`EmptyState`, `Badge`, `DataTable`)**: extracting them in this slice (rather than copy-pasting per page) means the next 5 dashboard slices — strategies, risk, costs, approvals, research-extras — drop into the same shape without re-extraction churn. `DataTable` in particular uses Svelte 5's `Snippet<[Row]>` typed cell slot for type-safe custom rendering + generic over `Row extends Record<string, unknown>`.
- **Row-click navigation via SvelteKit `goto`**: chosen over wrapping rows in `<a>` (which would break the nested-link a11y rule). Pair with `role="link"` + `tabindex={0}` + Enter/Space keyboard handler so keyboard users have parity with mouse users. Pattern reusable for any list-table-with-detail flow.
- **`loadError` as a string on page data**: 4xx/5xx + network throws all collapse to a single `loadError` string, page renders `<div role="alert">` without crashing. Same shape across the list page + detail page = predictable error UX.
- **`pnpm check` (svelte-check) 0 errors + 11 vitest cases green**: caught the strict-typing gotchas before push. The 3 warnings are all in pre-existing files unrelated to this slice.

## What didn't

- **Worktree isolation bug on Windows**: the parent agent spawned this slice with `isolation: "worktree"`. The agent's worktree was created correctly but file writes from the agent ended up in the MAIN checkout (not the worktree). Diagnosed mid-run by comparing `git status` from both. Stash-transferred α's work into its worktree to recover. Pre-flag: when spawning Agent on Windows, verify after first write that files actually landed in `.claude/worktrees/<id>/` and not in the parent's CWD. Possibly related to CWD inheritance semantics on win32 spawn. Sister slice β (same parent, same options) used its worktree correctly — making this non-deterministic, not a config error.
- **`test_trades_route_smoke.py` initial failures**: my first version of the smoke test defined its own `engine` / `client` / `seed` fixtures inline. Failed three times: (a) the seed used a single `sf()` block to insert Tenant + User but the slice-3 listener requires `with_tenant_context(...)` for the User insert; (b) `await client.get(url, cookies={...})` triggers httpx's deprecated-per-request-cookies warning, escalated to error by `filterwarnings = "error"`; (c) `Base.metadata.create_all` doesn't include the `trades` / `orders` / `fills` tables unless the trading models are imported (their `Mapped[...]` declarations register with the metadata at import time). Fixed (a) by mirroring `test_trade_routes.py`'s split-insert pattern; (b) by `client.cookies.set(...)` once + plain `get()`; (c) by `from iguanatrader.contexts.trading import models as _trading_models`. Final smoke 3/3 green. Pre-flag: when authoring new integration tests, REUSE the canonical `client` + `seeded_tenant_user` fixtures from `conftest.py` rather than duplicating them — saves all three fixes at once.

## Carry-forward

- **Pagination cursor in the UI** — backend returns `next_cursor: null` in v1 + the UI doesn't render a paginator. When backend gains pagination (v2 SaaS slice), add a "Cargar más" button + cursor passthrough.
- **Sortable column headers** — server already sorts by `created_at DESC`; client-side column-sort dropdown defers to follow-up.
- **Trade cancellation / state mutation** — read-only in this slice; mutation lives in `trades-mutation-ui` (separate slice).
- **SSE realtime updates** — page is `load`-fn driven; refresh requires nav. `trades-sse-realtime` is a separate slice once SSE infra extends to trades.
- **Per-tenant currency formatting** — commission display defaults to USD; currency dropdown is v1.5.

## Pattern usage

- **EmptyState component** — semantically distinct from `PlaceholderCard` (no "future slice" reference; this is real empty data). Will be the canonical empty-data card for the next 5 dashboard slices. Copy convention: "No <thing> aún. <action_hint>." + optional docs hint link.
- **Badge component + variant helper** — `sideVariant(side)` and `stateVariant(state)` are pure functions in `$lib/trades/variants.ts` — extracted so the mapping is unit-testable without a DOM. Pattern reusable for any enum→Badge mapping.
- **DataTable component** — generic over `Row extends Record<string, unknown>` with `DataTableColumn<Row>` config + optional `Snippet<[Row]>` cell renderer. `onRowClick` makes the row a `role="link"` with keyboard parity. The next dashboard slices reuse this without forking.
- **Catch-all error handling at the load fn** — every 4xx/5xx + network throw collapses to `loadError: string` on page data. Page renders alert OR data; no crash path.
- **Smoke-API + vitest pairing per dashboard slice** — backend smoke pins the contract shape (TradeListOut, RFC 7807 404, empty FillListOut); frontend vitest pins the rendering. Belt-and-braces against drift.
