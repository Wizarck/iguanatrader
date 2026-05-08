# Retrospective: trades-read-endpoints

> **Forward-authored** per [.ai-playbook/specs/runbook-bmad-openspec.md §4.1](../.ai-playbook/specs/runbook-bmad-openspec.md). Fields filled at archive time.

- **PR**: [#106](https://github.com/Wizarck/iguanatrader/pull/106) (merged 2026-05-08, squash `e9f70f1`).
- **Archive path**: `openspec/changes/archive/2026-05-08-trades-read-endpoints/`
- **Lines shipped**: 600 insertions / 32 deletions across 8 files (~80 src + ~290 tests + ~230 openspec/retro). CI 14/14 verde al primer push.

## What worked

- 3 GET stubs swapped to bodies in <30min via existing `TradeRepository.get_by_id` + 2 new methods (`list_for_tenant`, `list_for_trade`).
- Centralised `_seed_trade` helper in the test file kept setup terse + readable.
- `tenant_listener` (slice-3) handled cross-tenant isolation transparently — no explicit `WHERE tenant_id` needed in the new repository methods.
- 14/14 CI green at first push (lint+mypy+pytest+lighthouse+coderabbit). Local `.venv` ruff/black/mypy installed during P1-followup paid off.

## What didn't

- `_seed_trade` helper duplicates a small slice of what `TradingService` would do end-to-end; for v1 the test-local fixture keeps tests fast + isolated, but a future cleanup could reuse a shared seeding utility.

## Carry-forward

- Pagination cursor for `TradeListOut.next_cursor` — v2 SaaS slice when tenant trade volume > 1k rows.
- `GET /trades/orders/{order_id}` route + `OrderRepository.list_for_tenant` — defer to a per-order detail slice when the dashboard demands it.
- Same shape for `portfolio.py` + `strategies.py` route stubs (still 501) — separate slices.
