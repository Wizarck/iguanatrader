# Retrospective: trading-routes-and-daemon (T4 keystone — partial)

> **Forward-authored** per [.ai-playbook/specs/runbook-bmad-openspec.md §4.1](../.ai-playbook/specs/runbook-bmad-openspec.md). Fields filled at archive time.

- **PR**: TBD (slice/trading-routes-and-daemon branch open)
- **Archive path**: `openspec/changes/archive/<archive-date>-trading-routes-and-daemon/`
- **Lines shipped**: ~600 LoC src (vs ~1,200 estimated; integration test deferred to followup)

## What worked

- _(fill on archive — pre-flag candidates: T1 skeleton was extraordinarily helpful — handlers were already declared; T4 just filled bodies. The Wave 4 deferred 3.B.2 + 3.C.2 closed in 2 single lines as promised.)_

## What didn't

- _(fill on archive — pre-flag candidates: K1 RiskService + P1 ApprovalService have NO register_subscriptions methods → full pipeline can't be exercised end-to-end → integration test deferred → T4 ships incomplete. Discovery happened mid-apply, not in design phase.)_

## Lessons

- _(fill on archive — pre-flag candidates: pre-flight discovery gates B/C should include "does the consumer-side wiring of every event subscriber exist?" — not just "do I have the proposal/design/tasks". The discovery that K1+P1 lacked register_subscriptions surfaced AFTER design was approved.)_

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
