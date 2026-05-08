# Retrospective: trades-read-endpoints

> **Forward-authored** per [.ai-playbook/specs/runbook-bmad-openspec.md §4.1](../.ai-playbook/specs/runbook-bmad-openspec.md). Fields filled at archive time.

- **PR**: TBD
- **Archive path**: `openspec/changes/archive/<archive-date>-trades-read-endpoints/`
- **Lines shipped**: ~250 LoC (~50 src + ~280 tests).

## What worked

- _(fill on archive — pre-flag candidates: 3 GET stubs swapped to bodies in <30min via existing `TradeRepository.get_by_id` + 2 new methods (`list_for_tenant`, `list_for_trade`); `_FakeBroker`-style proposal-trade-order-fill seed helper centralised; tenant_listener took care of cross-tenant isolation transparently.)_

## What didn't

- _(fill on archive — pre-flag candidates: empty `_seed_trade` helper duplicates logic that exists in T4 service layer; future cleanup could reuse `TradingService` flow but for v1 a test-local seeding fixture keeps the test isolated.)_

## Carry-forward

- Pagination cursor for `TradeListOut.next_cursor` — v2 SaaS slice when tenant trade volume > 1k rows.
- `GET /trades/orders/{order_id}` route + `OrderRepository.list_for_tenant` — defer to a per-order detail slice when the dashboard demands it.
- Same shape for `portfolio.py` + `strategies.py` route stubs (still 501) — separate slices.
