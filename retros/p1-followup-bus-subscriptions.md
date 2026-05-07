# Retrospective: p1-followup-bus-subscriptions

> **Forward-authored** per [.ai-playbook/specs/runbook-bmad-openspec.md §4.1](../.ai-playbook/specs/runbook-bmad-openspec.md). Fields filled at archive time.

- **PR**: [#104](https://github.com/Wizarck/iguanatrader/pull/104) (merged 2026-05-07, squash `d0567b4`).
- **Archive path**: `openspec/changes/archive/2026-05-07-p1-followup-bus-subscriptions/`
- **Lines shipped**: 1018 insertions across 8 files (≈623 LoC src+test: 220 approval/service.py + 30 cli/trading.py + 403 test_service_bus_bridge.py; remaining 395 are openspec spec docs + retro stub).

## What worked

- **K1-followup pattern replicated verbatim** with one delta: 4 subscriptions instead of 1 (1 inbound + 3 outbound bridges). Two recurrences confirm the bus-bridge follow-up pattern is the canonical fix for archive-additive cross-context wiring.
- **Gates A/B/C explicit approval workflow** (lesson from deployment-foundation retro) again paid off — zero re-work between proposal → design → tasks → apply.
- **`metadata: dict[str, Any]` field absorbed cross-context schema mismatches**: `trading.ProposalApproved` doesn't have `decision_id`/`decided_at`/`decided_via_channel` slots; the metadata dict held them as forensic fields without rotating the archive event shape.
- **ContextVar tenant-resolution fallback** (`tenant_id_var.get() → log+skip on None`) is now an established pattern at bus-bridge boundaries — added test 7 was the new test-design wrinkle vs K1.
- **Daemon log line went from `trading.daemon.bus_subscriptions.partial` (warning) → `trading.daemon.bus_subscriptions.complete` (info)** — fully closes the operator-visible gap left by T4.
- **CI 14/14 pass after one black-format fix** — only fail was lint (black --check); ruff + mypy + pytest all green at first push. Quick-fix iteration: install black+ruff into local `.venv`, format, single-line commit, re-push.

## What didn't

- **`.venv` lacked the dev tools** (black/ruff/mypy/pytest absent — only pip installed). The black-format mismatch was caught only at CI, costing one re-push cycle. Mitigation already applied: black + ruff installed in `.venv` so the next slice can run them locally before push. Permanent fix candidate: a `make bootstrap-dev` target or a documented `pip install black ruff mypy pytest` step.
- **Cross-context event schema mismatch discovered at code-write time**: `trading.ProposalApproved` schema does NOT carry `decision_id`/`decided_at`/`decided_via_channel` (only `tenant_id`/`proposal_id`/`approved_by_user_id`/`metadata`). Pre-flight grep of cross-context event constructors before drafting the bridge handler would have caught this earlier — same lesson as K1-followup's `CapType` literal discovery. Mitigation: future bus-bridge slices should grep destination-event constructors during design phase (Gate B), not during apply.

## Lessons

- **Bus-bridge follow-up pattern is now battle-tested twice** (K1-followup PR #103 + this slice). Two recurrences justify promotion to ai-playbook v0.11.1 as a named pattern. Method shape: `register_subscriptions(bus) → 1 inbound handler (audit-write) + N outbound bridge handlers (translate context-A events to context-B events using ContextVar for tenant resolution)`.
- **Cross-context event schema mismatches** are absorbed by the destination event's `metadata: dict[str, Any]` field. Adding a field to an archived event class would rotate the on-the-wire shape; the metadata dict is the canonical escape hatch.
- **ContextVar tenant resolution** is a recurring pattern at bus-bridge boundaries. The `tenant_id_var.get() → log+skip on None` shape is now established as the canonical fallback (vs raising or emitting a tenant-less event).

## Carry-forward to next change

- **T4-followup**: integration test now possible — full propose→risk→approve→execute path runnable in a single test (K1 + P1 hops both closed). Strategy resolver production wiring (`_make_strategy_resolver` `NotImplementedError` placeholder in `cli/trading.py`) also lands there.
- **P1-followup-channel-fanout** (deferred, optional): if/when the operator UX requires Telegram bot push or Hermes WhatsApp HTTP send (vs dashboard SSE click-to-approve), this slice adds a `ChannelDispatcher` injected into `ApprovalService._approval_requested_handler`. Out of scope for this slice — the bus chain closes regardless of push-fan-out.
- **ai-playbook v0.11.1 promotion**: capture the bus-bridge follow-up pattern formally in the playbook now that K1-followup + P1-followup confirm recurrence.

## Pattern usage

This slice is the **second canonical instance** of the "bus-bridge follow-up" pattern. The shape used here (1 inbound `register_subscriptions` wire + N outbound bridge handlers + ContextVar tenant resolution + metadata-dict for forensic field stashing) is the recommended template for future archive-additive bus-bridges.

## Acceptance status (operator-driven, post-merge)

- [x] mypy --strict + pre-commit + CI green (14/14 pass after one black-format fix push).
- [ ] Daemon boots emitting `trading.daemon.bus_subscriptions.complete` (no `partial` warning) — operator-verified at next paper-mode run.
- [ ] Manual proposal creation in paper mode → bus emits chain `ProposalCreated → ProposalRiskEvaluated → ApprovalRequested → approval_requests row INSERTed → operator clicks dashboard SSE → POST /approvals/{id}/approve → ApprovalProposalApproved → trading.ProposalApproved → broker.place_order` — operator-verified end-to-end (T4-followup integration test will automate this).
