# Retrospective: k1-followup-bus-subscriptions

> **Forward-authored** per [.ai-playbook/specs/runbook-bmad-openspec.md §4.1](../.ai-playbook/specs/runbook-bmad-openspec.md). Fields filled at archive time.

- **PR**: TBD (slice/k1-followup-bus-subscriptions branch open)
- **Archive path**: `openspec/changes/archive/<archive-date>-k1-followup-bus-subscriptions/`
- **Lines shipped**: ~250 LoC (115 src + 135 tests).

## What worked

- _(fill on archive — pre-flag candidates: T4-followup discovery in design.md was correct: K1 register_subscriptions was a 3-method additive change; lazy imports kept blast radius minimal; bridge pattern preserved K1's archived event surface intact.)_

## What didn't

- _(fill on archive — pre-flag candidates: had to re-discover K1's CapType literal values + KillSwitchActiveError import path during test authoring; could pre-flight grep before writing tests.)_

## Lessons

- **Bus-bridge follow-up pattern** is now validated (this is the first instance; P1-followup will be the second). Promote to ai-playbook v0.11.1 as a named pattern: when a previous slice publishes events expected by another slice's subscriber, the bridge handler is the canonical fix. Method shape: `register_subscriptions(bus) → handler(event) → load consumer-side data → invoke service method → publish translation event`.

## Carry-forward to next change

- **P1-followup**: same bus-bridge pattern, but for `ApprovalService.register_subscriptions(bus)` subscribing to `ApprovalRequested` → channel dispatch → `ProposalApproved` / `ProposalRejected`.
- **T4-followup**: integration test now possible — full propose→risk→approve→execute path can be exercised once P1 lands too.

## Pattern usage

This slice is the **canonical instance** of the "bus-bridge follow-up" pattern. The `RiskService.register_subscriptions` + `_proposal_created_handler` shape is replicable verbatim for P1-followup with `ApprovalRequested` → channel dispatch → `ProposalApproved`/`ProposalRejected`.

## Acceptance status (operator-driven, post-merge)

- [ ] Daemon boots without the K1 partial-warning (only P1 remains).
- [ ] Manual proposal creation → bus emits `ProposalCreated` → `ProposalRiskEvaluated` → T4's `risk_check_handler` reacts.
- [ ] mypy --strict + pre-commit + CI green.
