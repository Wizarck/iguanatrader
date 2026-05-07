## Why

T4 (`trading-routes-and-daemon`, archived 2026-05-07) shipped the keystone wiring + handler bodies + manual-approve route, but discovered mid-apply that **K1 RiskService has no `register_subscriptions(bus)` method**. The propose→risk→approve→execute pipeline is therefore broken at the propose→risk hop:

* T1 `TradingService.propose` publishes `ProposalCreated` on the bus.
* K1 `RiskService.evaluate_proposal(proposal: TradeProposalInput)` is the consumer — but nothing subscribes to `ProposalCreated` on its behalf.
* K1's published events (`RiskProposalAccepted` / `RiskProposalRejected`) ALSO don't match T1's expected event class (`ProposalRiskEvaluated`); T4's `risk_check_handler` would never fire even if K1 did publish.

**Without this slice, the only way the pipeline can fire is via T4's manual-approve route**, which bypasses risk evaluation entirely — no risk caps enforced on operator overrides. K1-followup closes the propose→risk hop so risk gating is mandatory on every order.

## What Changes

- **`RiskService.register_subscriptions(bus: MessageBus) -> None`** (NEW method on the existing `RiskService` class) — subscribes to `trading.ProposalCreated` and triggers `evaluate_proposal` per event. Idempotency-keyed by `proposal_id` per the bus's `idempotent=True` contract.
- **`_proposal_created_handler(event: ProposalCreated) -> None`** (NEW private async method on `RiskService`) — loads the `TradeProposal` row by id, projects to `TradeProposalInput`, calls `evaluate_proposal`, then **bridges** the K1 outcome to T1's expected event:
  - On allow/clip → publish `trading.ProposalRiskEvaluated(outcome="allow"|"clip", cap_type_breached=...)`.
  - On reject → publish `trading.ProposalRiskEvaluated(outcome="reject", cap_type_breached=decision.cap_type_breached)`.
  - K1 ALSO continues to publish its native `RiskProposalAccepted`/`RiskProposalRejected` events (no behaviour change for existing K1 subscribers).
- **`TradeProposalInput` projector helper** in K1 (`risk/service.py`) — converts the `TradeProposal` ORM row to K1's `TradeProposalInput` dataclass. Keeps the K1 service free of trading-context ORM imports at use sites; tests inject mocked TradeProposalInputs.
- **Out of scope**: P1 ApprovalService bus subscriptions (their own follow-up slice). Strategy resolver production wiring (T4-followup). Per-symbol propose loops (T4-followup). Integration test (T4-followup).

## Capabilities

- `risk`: gains `register_subscriptions(bus)` + the bridge handler; no new public-API surface beyond that.

## Impact

- **No K1-archive surface modified** — additive only (new method on existing class). The existing `RiskProposalAccepted` / `RiskProposalRejected` events still fire identically.
- **`ProposalRiskEvaluated` from `trading/events.py`** is now published by K1 (additive consumer).
- **No migrations** — pure code change.
- **Tests**: 4 unit tests covering the bridge handler (allow → ProposalRiskEvaluated allow, reject → ProposalRiskEvaluated reject, kill-switch active, malformed input).

## Prerequisites

T4 archived (2026-05-07) so `trading.events.ProposalRiskEvaluated` is importable + `T4 risk_check_handler` is the consumer. R5 + T1 + T3 archived (provide `TradeProposal` + `TradeProposalInput` + idempotency-key contracts).

## Out of scope

- P1 ApprovalService `register_subscriptions` (follow-up).
- Strategy resolver production wiring (T4-followup).
- Per-symbol propose loops (T4-followup).
- Integration test exercising propose→risk→approve→execute end-to-end (T4-followup).
- Hot-reloading of risk caps at runtime (existing K1 behaviour: caps are read on each evaluation; no daemon restart needed).

## Acceptance

- `RiskService.register_subscriptions(bus)` registers the `ProposalCreated → _proposal_created_handler` subscription idempotently.
- `_proposal_created_handler` loads `TradeProposal` by id, calls `evaluate_proposal`, and emits BOTH the K1-native event AND `trading.ProposalRiskEvaluated` matching T1's `risk_check_handler` expectation.
- 4 unit tests pass: allow path, reject path, kill-switch path, malformed input.
- mypy --strict + ruff + black clean.
- T4-followup integration test (separate slice) exercises the full propose→risk path against this slice's wiring.
