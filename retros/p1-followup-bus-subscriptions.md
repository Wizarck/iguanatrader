# Retrospective: p1-followup-bus-subscriptions

> **Forward-authored** per [.ai-playbook/specs/runbook-bmad-openspec.md §4.1](../.ai-playbook/specs/runbook-bmad-openspec.md). Fields filled at archive time.

- **PR**: TBD (slice/p1-followup-bus-subscriptions branch open)
- **Archive path**: `openspec/changes/archive/<archive-date>-p1-followup-bus-subscriptions/`
- **Lines shipped**: ~415 LoC (~145 src + ~210 tests + ~60 retro/openspec).

## What worked

- _(fill on archive — pre-flag candidates: K1-followup pattern replicated verbatim with one delta — 4 subscriptions instead of 1 (1 inbound + 3 outbound bridges); ContextVar fallback test added a new test-design wrinkle vs K1; trading-event metadata-dict pattern absorbed P1 fields that don't have a top-level slot in trading.ProposalApproved/Rejected; daemon log line went from `partial` warning → `complete` info — fully closes the operator-visible gap left by T4.)_

## What didn't

- _(fill on archive — pre-flag candidates: had to discover at code-write time that `trading.ProposalApproved` schema does NOT carry `decision_id`/`decided_at`/`decided_via_channel` (only `tenant_id`/`proposal_id`/`approved_by_user_id`/`metadata`); resolution: stash forensic fields in `metadata` dict. Could pre-flight grep cross-context event schemas before drafting bridge handler.)_

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

- [ ] Daemon boots emitting `trading.daemon.bus_subscriptions.complete` (no `partial` warning).
- [ ] Manual proposal creation in paper mode → bus emits chain `ProposalCreated → ProposalRiskEvaluated → ApprovalRequested → approval_requests row INSERTed → operator clicks dashboard SSE → POST /approvals/{id}/approve → ApprovalProposalApproved → trading.ProposalApproved → broker.place_order`.
- [ ] mypy --strict + pre-commit + CI green.
