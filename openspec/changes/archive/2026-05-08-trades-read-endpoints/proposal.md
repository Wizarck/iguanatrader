# Proposal: trades-read-endpoints

> Fill the 3 stub GET endpoints in `apps/api/src/iguanatrader/api/routes/trades.py` (currently 501 `NotImplementedFeatureError`). Pure read-only; no migrations; no new repository methods.

## Why

Slice T4 (`trading-routes-and-daemon`, archived 2026-05-07) shipped the keystone partial-scope: the operator-override `POST /proposals/{id}/approve` route + the daemon. Three GET stubs in `trades.py` were left at 501 (`list_trades`, `get_trade`, `list_trade_fills`) — they block:

- The dashboard's `/trades` page from listing tenant trades.
- Postmortem ops queries (`curl /api/v1/trades/{id}`).
- Future replay/audit slices that need to read the trades+fills surface.

The repositories (`TradeRepository.get_by_id`, `FillRepository`) already exist from T1 + T4. This slice is exclusively about wiring the 3 route bodies + a thin list query.

Out of scope: portfolio + strategies route stubs (separate slices), order CRUD, write surface.

## What

Three additive route-body fills:

1. **`GET /trades`** — `list_trades(user)`: SELECT all trades for the current tenant ordered by `created_at DESC`, returns `TradeListOut`. Cursor-based pagination is OUT OF SCOPE for v1 (returns full list; cursor field always null). v1 watchlist of 3 symbols × ~20 trades/year = trivial.
2. **`GET /trades/{trade_id}`** — `get_trade(trade_id, user)`: 200 `TradeOut` on hit, 404 NotFoundError on miss. Tenant filter automatic via slice-3 `tenant_listener`.
3. **`GET /trades/{trade_id}/fills`** — `list_trade_fills(trade_id, user)`: SELECT fills WHERE order_id IN (SELECT id FROM orders WHERE trade_id = :trade_id), ordered by `filled_at ASC`, returns `FillListOut`. Empty list if no fills yet (NOT 404 — a trade with no fills is a valid in-flight state).

Repository additions:

- `TradeRepository.list_for_tenant() -> list[Trade]` — NEW.
- `FillRepository.list_for_trade(trade_id) -> list[Fill]` — NEW (joins via `Order.trade_id`).

Out of scope (deferred):

- Pagination cursor (v1 uses null cursor; v2 SaaS adds when tenant trade volume > 1k rows).
- Sorting/filtering query params (v2 dashboard slice).
- `GET /trades/orders/{order_id}` — declared in the carry-forward but NOT in `trades.py`; would need a NEW route file. Defer to a future micro-slice when the dashboard demands per-order detail.

## Acceptance criteria

1. `list_trades` returns `TradeListOut(items=[...], total=len(items), next_cursor=None)` with all tenant trades sorted by `created_at DESC`.
2. `get_trade(trade_id)` returns 200 `TradeOut` for a known id, 404 with `NotFoundError(detail=...)` for missing.
3. `list_trade_fills(trade_id)` returns `FillListOut` of all fills for orders linked to the trade, sorted by `filled_at ASC`.
4. mypy --strict + ruff + black + pre-commit + CI all green.
5. ≥4 unit tests covering: list (non-empty), list (empty), get (hit), get (miss → 404), list_trade_fills (joined fills).

## Blast radius

Zero archive-surface modification. Pure additive on `trades.py` route bodies + 2 new repository methods on already-existing classes. No event emissions, no migrations, no schema changes. `__all__` list unchanged.

## Effort

~2-3h, ~150 LoC (~80 src + ~120 tests + ~30 openspec/retro).
