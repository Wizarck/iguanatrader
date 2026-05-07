# Retrospective: k1-followup-bus-subscriptions

> **Forward-authored** per [.ai-playbook/specs/runbook-bmad-openspec.md §4.1](../.ai-playbook/specs/runbook-bmad-openspec.md). Fields filled at archive time.

- **PR**: [#103](https://github.com/Wizarck/iguanatrader/pull/103) (merged 2026-05-07, squash `cfc1ce5`).
- **Archive path**: `openspec/changes/archive/2026-05-07-k1-followup-bus-subscriptions/`
- **Lines shipped**: 750 insertions across 8 files (≈436 LoC src+test: 127 risk/service.py + 23 cli/trading.py + 286 test_service_bus_bridge.py; remaining 314 are openspec spec docs + retro stub).

## What worked

- **Pre-flag candidates confirmed**: T4-followup discovery in design.md was correct — K1 `register_subscriptions` was a clean 3-method additive change; lazy imports kept the blast radius minimal; bridge pattern preserved K1's archived event surface (`RiskProposalAccepted`/`Rejected`) intact while emitting the new T1-expected `ProposalRiskEvaluated`.
- **Gates A/B/C explicit approval workflow** (lesson from deployment-foundation retro) again paid off: zero re-work between proposal → design → tasks → apply.
- **CI green at first push**: 14/14 checks passed including mypy --strict, ruff, black, gitleaks, Helm lint, Lighthouse, CodeRabbit (+ L2 fallback). Pattern-matches T4 outcome.
- **Bus-bridge follow-up pattern** is now battle-tested for the second time (T4 keystone wiring + K1-followup bridge); promotion to ai-playbook v0.11.1 as a named pattern is well justified.

## What didn't

- **Pre-flight grep cost ~2 cycles**: had to re-discover K1's `CapType` literal values (`per_trade`/`daily_loss`/`weekly_loss`/`max_open`/`max_drawdown` — not the assumed `"daily"`) and the `KillSwitchActiveError` canonical import path (`iguanatrader.shared.errors`, not re-exported by `risk.service`) during test authoring. Mitigation: before writing the next bus-bridge test file (P1-followup), grep the imported types' definition site first.
- **`RiskRepository(session=session)` constructor signature** required a one-shot mypy fix (positional arg). Could have been pre-empted by reading the repo class signature before drafting daemon wiring; same mitigation as above.

## Lessons

- **Bus-bridge follow-up pattern** is now validated (this is the first instance; P1-followup will be the second). Promote to ai-playbook v0.11.1 as a named pattern: when a previous slice publishes events expected by another slice's subscriber, the bridge handler is the canonical fix. Method shape: `register_subscriptions(bus) → handler(event) → load consumer-side data → invoke service method → publish translation event`.

## Carry-forward to next change

- **P1-followup**: same bus-bridge pattern, but for `ApprovalService.register_subscriptions(bus)` subscribing to `ApprovalRequested` → channel dispatch → `ProposalApproved` / `ProposalRejected`.
- **T4-followup**: integration test now possible — full propose→risk→approve→execute path can be exercised once P1 lands too.

## Pattern usage

This slice is the **canonical instance** of the "bus-bridge follow-up" pattern. The `RiskService.register_subscriptions` + `_proposal_created_handler` shape is replicable verbatim for P1-followup with `ApprovalRequested` → channel dispatch → `ProposalApproved`/`ProposalRejected`.

## Acceptance status (operator-driven, post-merge)

- [x] mypy --strict + pre-commit + CI green (14/14 at first push).
- [ ] Daemon boots without the K1 partial-warning (only P1 remains) — operator-verified at next paper-mode run.
- [ ] Manual proposal creation → bus emits `ProposalCreated` → `ProposalRiskEvaluated` → T4's `risk_check_handler` reacts — operator-verified end-to-end (K1 hop closed; T4 → P1 hop still bypassed by manual-approve route until P1-followup ships).
