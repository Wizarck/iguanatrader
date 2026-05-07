# Retrospective: trading-routes-and-daemon (T4 keystone — partial)

- **Archived**: 2026-05-07
- **PR**: [#102](https://github.com/Wizarck/iguanatrader/pull/102) — squash-merged at `0f97bd4`.
- **Archive path**: `openspec/changes/archive/2026-05-07-trading-routes-and-daemon/`
- **Schema**: spec-driven
- **Lines shipped**: ~600 LoC src + 50 retro/tasks ≈ **~650 total** (vs ~1,200 estimated; integration test deferred to followup).

## What worked

- **T1 skeleton paid off massively**. `TradingService` + 6 handler stubs were already declared with `# T4 fills` markers — T4 just filled bodies. Saved an estimated 200-300 LoC of class-shape authoring + bus-subscription declarations. Pattern candidate: **pre-shipped skeletons for bus-event-driven services accelerate downstream slices by 3-5x**.
- **Wave 4 deferred items closed in single lines as promised** (3.B.2 IBKRAdapter ← IbAsyncIBClient + 3.C.2 OrchestrationService ← APSchedulerAdapter). The `build_*_from_env()` factory pattern from deployment-foundation worked cleanly — daemon entrypoint reads like a documentation example.
- **Gates A/B/C followed explicitly** (proposal review → design review → tasks review) — fixing the workflow lesson from deployment-foundation retro. Operator approved each gate consciously (`adelante` → next gate). Zero rework from skipping.
- **Local mypy/ruff/black before each commit** → CI green at first push (15/15 checks pass). Compare to deployment-foundation slice: 4 rounds of fix-iterations. Lessons codified worked.
- **Design pivot during apply** (rejection event-only when `trade_proposals` revealed strict-append-only) was caught at handler-body authoring time, not in production. The pivot was a 5-minute decision documented in the repository docstring + tasks.md notes.

## What didn't

- **K1 + P1 `register_subscriptions` absence surfaced AFTER design approval**. K1 RiskService + P1 ApprovalService were scaffolded in their own slices but their bus integrations were never completed. T4 design assumed they existed; discovery happened during Group 3 daemon authoring. Forced partial-scope: integration test deferred + manual-approve route as keystone interim path.
- **Strategy resolver production wiring forced a `NotImplementedError` stub**. T4 design assumed a `StrategyManager.get_strategy(id)` method exists; doesn't. The closure scaffold raises NotImplementedError and tests bypass via direct injection. Deferred to T4-followup.
- **Integration test ALL deferred** — 5 sub-tasks (5.1-5.5) all moved to T4-followup because the full pipeline (synthesise → propose → risk → approve → execute) can't be exercised without K1+P1 wiring. T4 ships keystone DI + bodies + manual-approve only.
- **Pre-flight discovery missing from Gate B (design review)**. The "does every consumer-side wiring of every event subscriber exist?" question wasn't asked. Promote to ai-playbook v0.11.1 as a hard Gate-B checklist item.

## Lessons

- **Pre-flight discovery for bus-driven slices** must answer "for every event we plan to publish, who consumes it AND is the subscription wiring already shipped?" — BEFORE Gate B approval. Add to ai-playbook `runbook-bmad-openspec.md` Gate B checklist.
- **Strict-append-only schemas need a documented reaching-around pattern**. Three options surfaced: (a) add a migration to allow column mutation via `__append_only_mutable_columns__`, (b) track state via separate audit table, (c) track state via bus events only. T4 picked (c) — works for transient lifecycles but breaks queryability for ops dashboards. The choice is per-table; the pattern is "state is event-derived, not column-mutable".
- **Skeleton + body-fill pattern is the new Wave normal**. T1 → T4 (fill) is the second iteration of this (R1 → R5 was the first; deployment-foundation's adapters were the third). Promote to ai-playbook as **`skeleton-then-fill.md`** named pattern.
- **`object`-typed callable params should use proper type aliases**. Five mypy errors in the daemon traced to `object` param types where `StrategyResolver` / `IbAsyncIBClient` would have given mypy enough info. Cost: 10 minutes of cast() insertions. Lesson: when authoring a daemon with multiple injected services, declare type aliases first, then write the body.

## Carry-forward to next change(s)

- **T4-followup slice** — the integration test (synthesise → propose → risk → approve → execute → fill → equity-snapshot end-to-end). Requires K1+P1 wiring landed first.
- **K1-followup slice** — `RiskService.register_subscriptions(bus)` that wires `bus.subscribe(ProposalCreated, evaluate_proposal_handler)`.
- **P1-followup slice** — `ApprovalService.register_subscriptions(bus)` that wires `bus.subscribe(ApprovalRequested, channel_dispatch_handler)` + handles operator decisions returning `ProposalApproved`/`ProposalRejected`.
- **Strategy resolver production wiring** — `cli/trading.py:_make_strategy_resolver` currently raises `NotImplementedError`; followup wires `StrategyConfigRepository.get(id) → manager._get_or_build`.
- **Per-symbol propose loops in OrchestrationService.bootstrap_routines** — currently registers placeholder fn; followup iterates `watchlist_symbols` per cron tick.
- **Trades+orders read endpoints** (`GET /trades/{id}`, `GET /trades/{id}/fills`, `GET /trades/orders/{id}`) — T1 stubs still 501; followup fills bodies.
- **Schema observation**: `trade_proposals.state` column would simplify the rejection-tracking pattern. Currently rejection is event-only (per slice T4 design pivot). If we ever need queryable rejection state for ops dashboards, a follow-up migration to add `state` column with `__append_only_mutable_columns__` is the documented path.

## Pattern usage

T4 IS the canonical "**deferred-DI closure**" example for the
[protocol-fake-deferred-install.md](../.ai-playbook/specs/protocol-fake-deferred-install.md) pattern: deployment-foundation
shipped the production adapters with `build_*_from_env()` factories,
leaving the DI wiring to T4. T4 closes 2 of the 3 deferred items
in single-line wirings (3.B.2 IBKRAdapter, 3.C.2 APSchedulerAdapter).

## Acceptance status (operator-driven, post-merge)

- [ ] Daemon smoke: `iguanatrader trading run --mode paper --tenant <slug>` boots + accepts SIGTERM
- [ ] Manual approve flow: synthesise a proposal manually → POST /proposals/{id}/approve → verify Order row + OrderPlaced event
- [ ] Mypy --strict clean (verified locally; CI will reconfirm)

When the operator validates the manual-approve flow + the K1/P1
followup slices land + the T4-followup integration test passes, the
keystone is complete.
