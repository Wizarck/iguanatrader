# Proposal: p1-followup-bus-subscriptions

> **Bus-bridge follow-up** — second canonical instance of the pattern (K1-followup was the first; promote to ai-playbook v0.11.1 as a named pattern). Pure additive on `ApprovalService`. Zero archive-surface modification.

## Why

Slice T4 (trading-routes-and-daemon, merged 2026-05-07) ships the daemon that wires bus subscribers, but **P1 `ApprovalService` lacks `register_subscriptions(bus)`**, so the propose→risk→**approval**→execute pipeline still has a gap between `trading.ApprovalRequested` and `trading.ProposalApproved`/`ProposalRejected`. T4's daemon emits a partial-warning log line acknowledging this and routes operator overrides via `POST /trades/proposals/{id}/approve` (manual bypass).

K1-followup (merged 2026-05-07, PR #103) closed the equivalent gap on the K1 side using the bus-bridge pattern. This slice replicates it on the P1 side:

1. **Inbound**: ApprovalService subscribes to `trading.ApprovalRequested` → calls `create_request` (audit-write the row that `POST /approvals/{id}/{approve,reject}` routes already look up).
2. **Outbound bridge**: ApprovalService re-emits `approval.ApprovalProposalApproved/Rejected/TimedOut` as the trading-flavored `trading.ProposalApproved/ProposalRejected` events that T4's `execute_on_approval_handler` + `proposal_rejected_handler` already subscribe to.

After this slice, the bus chain `ProposalCreated → ProposalRiskEvaluated → ApprovalRequested → ApprovalProposalApproved → ProposalApproved → broker.place_order` closes end-to-end without any handler being a no-op or external POST being required.

## What

Pure additive on `apps/api/src/iguanatrader/contexts/approval/service.py` — three new methods, zero changes to existing audit-surface (P1 events `ApprovalProposalApproved/Rejected/TimedOut` continue to fire byte-for-byte unchanged for dashboard/SSE/audit consumers):

1. `register_subscriptions(bus: MessageBus | None = None) -> None` — public, idempotent registration. Subscribes:
   - `trading.ApprovalRequested → self._approval_requested_handler` (idempotent)
   - `approval.ApprovalProposalApproved → self._bridge_to_trading_approved_handler` (idempotent)
   - `approval.ApprovalProposalRejected → self._bridge_to_trading_rejected_handler` (idempotent)
   - `approval.ApprovalProposalTimedOut → self._bridge_to_trading_rejected_handler` (idempotent — timeout collapses to `ProposalRejected(reason="approval_timeout")`)
2. `_approval_requested_handler(event: ApprovalRequested) -> None` — async. Calls `self.create_request(proposal_id=event.proposal_id, channels=DEFAULT_CHANNELS, timeout_seconds=DEFAULT_TIMEOUT_SECONDS)`. Reads `IGUANATRADER_DEFAULT_APPROVAL_CHANNELS` (CSV; default `"telegram,dashboard"`) + `IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS` (int; default `300`) at call time (env-var-first-cut per slice T4 §3.3.g pattern; v2 SaaS swaps to a per-tenant table).
3. `_bridge_to_trading_approved_handler` + `_bridge_to_trading_rejected_handler` — async. On `ApprovalProposalApproved` → publish `trading.ProposalApproved(tenant_id, proposal_id, decision_id, decided_at)`. On `ApprovalProposalRejected | ApprovalProposalTimedOut` → publish `trading.ProposalRejected(tenant_id, proposal_id, reason)`. Tenant-id resolution: read from `tenant_id_var` ContextVar (slice 2 D2 pattern) since approval events themselves do not carry `tenant_id`.

Daemon update (`apps/api/src/iguanatrader/cli/trading.py`): construct `ApprovalService(repository=ApprovalRepository(), message_bus=bus)` and call `approval_service.register_subscriptions(bus)` after `risk_service.register_subscriptions(bus)`. Drop `P1` from the `trading.daemon.bus_subscriptions.partial` warning (it becomes a no-op log line — remove it entirely).

## Out of scope

- **Channel push fan-out**: Telegram/Hermes/dashboard channels are NOT triggered by the bus-bridge handler. Operators continue to drive decisions via `POST /approvals/{request_id}/{approve,reject}` routes (which already exist) or via dashboard SSE click. Push-fan-out (Telegram bot send, WhatsApp Hermes send) is a separate slice — call it `P1-followup-channel-fanout` if/when the operator UX warrants it. The bus chain closure does NOT require channel push.
- **T4-followup integration test**: end-to-end `propose → risk → approve → execute` integration test is enabled by this slice but lives in `T4-followup`.
- **Per-tenant channel + timeout configuration**: env-var-first-cut is the ship; per-tenant `approval_defaults` table is a v2 SaaS slice.

## Acceptance criteria

1. `ApprovalService(repository, message_bus).register_subscriptions(bus)` registers four subscriptions on the bus (one inbound + three outbound bridges).
2. Publishing `trading.ApprovalRequested(tenant_id, proposal_id, decision="allow")` results in exactly one `approval_requests` row INSERTed (via `ApprovalRepository.create_request`) and one `approval.request.created` log line.
3. Publishing `approval.ApprovalProposalApproved(proposal_id, decision_id, decided_at, decided_via_channel="telegram")` results in exactly one `trading.ProposalApproved` event published with the same `proposal_id` + `decision_id` and `tenant_id` resolved from the ContextVar.
4. Publishing `approval.ApprovalProposalRejected(proposal_id, decision_id, decided_at, reason="user_declined")` results in exactly one `trading.ProposalRejected` published with `reason="user_declined"`.
5. Publishing `approval.ApprovalProposalTimedOut(proposal_id, request_id, expired_at)` results in exactly one `trading.ProposalRejected` published with `reason="approval_timeout"`.
6. Daemon boot log no longer emits the `trading.daemon.bus_subscriptions.partial` warning (the partial-scope flag is fully resolved).
7. `mypy --strict` + `ruff` + `black` + `pre-commit` + CI all green.

## Pattern usage

This is the **second canonical instance** of the bus-bridge follow-up pattern (K1-followup was the first). The shape of `register_subscriptions` + per-event handler + cross-context event re-emission is replicable verbatim. After this slice ships, promote the pattern to `ai-playbook` v0.11.1 as a named pattern:

> **Bus-bridge follow-up**: when slice A ships a service that publishes events expected by slice B's subscriber but slice A was archived before slice B existed, the canonical fix is a `register_subscriptions` method on slice A's service plus per-event bridge handlers that translate slice-A-flavored events to slice-B-flavored events. Pure additive; zero archive-surface modification; lazy imports for cross-context type isolation.

## Blast radius

Zero archive-surface modification. P1's existing `ApprovalProposalApproved/Rejected/TimedOut` event consumers (audit log, dashboard SSE, observability) are untouched — those events continue to fire byte-for-byte. The new bridge subscribers ride the same publication. The K1-followup slice has already validated the lazy-import + idempotent-subscribe pattern at runtime.
