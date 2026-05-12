# Proposal: property-tests-bus-bridge-handlers

> **Test-only slice** — Hypothesis property regression net for the K1+P1 bus-bridge handlers (`RiskService._proposal_created_handler` + `ApprovalService._approval_requested_handler`). Companion to `propose-event-emission-property` (PR #112) which covers `TradingService.propose`. Zero runtime code changes.

## Why

PR #112 shipped a property test for the propose→bus emission contract. The retro flagged the analogous regression net for the two downstream handlers:

> **Property tests for K1+P1 bus-bridge handlers** — analogous shape but on `RiskService._proposal_created_handler` + `ApprovalService._approval_requested_handler`. Could ship as a 4th `tests/property/` file.

The handlers are bus subscribers in the propose→risk→approve→execute chain. A regression where one of them silently double-emits, silently drops, or escapes an exception would corrupt the chain in ways unit tests would miss on randomised inputs. The new property tests cover:

- **`RiskService._proposal_created_handler`**:
  - 1:1 emission of `ProposalRiskEvaluated` per `ProposalCreated` when the proposal exists.
  - Zero emission when the `TradeProposal` row is missing (defensive path; event was for a deleted proposal).
  - `outcome='reject'` + `cap_type_breached='kill_switch'` when `evaluate_proposal` raises `KillSwitchActiveError` (the kill-switch must drive the proposal to a terminal state, not leave it in-flight).

- **`ApprovalService._approval_requested_handler`**:
  - Exactly 1 `create_request` call per `ApprovalRequested`.
  - Exactly 1 `dispatcher.fanout(request, channels)` invocation when a dispatcher is wired.
  - Zero fanout calls when `channel_dispatcher=None` (PR #111 backward-compat path).
  - FR32 isolation: handler does NOT re-raise when `dispatcher.fanout` raises.

## What

Two new property test files under `apps/api/tests/property/`:

1. `test_risk_proposal_created_handler.py` — 3 Hypothesis properties (50 examples each).
2. `test_approval_requested_handler.py` — 4 Hypothesis properties (50 examples each).

Both reuse the existing `tests/property/` conventions:

- `@pytest.mark.property` marker (not `ci_blocking` — emission contract already covered by unit tests; this is the regression net).
- Sync test functions wrapping `async def _run()` inside `asyncio.run(...)` (the canonical async-property-test shape per #112 retro).
- `@given(...)` over random UUIDs + payload fields; `@settings(deadline=None, max_examples=50, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])`.
- Fake bus subscriber that captures published events into a list (`_FakeBus` not needed — uses real `MessageBus`).
- Fake repositories (`AsyncMock`) for the proposal-row + approval-request lookups.

## Out of scope

- **Stateful Hypothesis tests** (multi-tick sequences `propose → publish → consume → re-propose`) — already deferred to v2 backtest-engine per PR #112 retro.
- **Property tests for the 3 outbound bridges** in `ApprovalService` (`_bridge_to_trading_{approved,rejected,timeout}_handler`) — analogous shape but adds 3 more files; defer if scope risks. The single `_approval_requested_handler` test is the critical-path coverage; the bridges are simpler shape-preserving translations.
