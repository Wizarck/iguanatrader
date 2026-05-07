# tasks — k1-followup-bus-subscriptions

> Order: 1 → 2 → 3 → 4 → 5. Each group has 1-3 sub-tasks. Slot reservations per [.ai-playbook/specs/migration-slot-reservation.md](../../../.ai-playbook/specs/migration-slot-reservation.md): no migrations claimed; pure additive code.
>
> Pattern usage: this slice is the canonical "**bus-bridge follow-up**" — additive wiring on an already-archived service. Promote to ai-playbook v0.11.1 if recurrence (P1-followup will be the second instance, expected).

## 1. RiskService body fills (`apps/api/src/iguanatrader/contexts/risk/service.py`)

- [ ] **1.1** Add static method `_project_proposal_input(row: TradeProposal) -> TradeProposalInput` that maps ORM → DTO and computes `notional_value = quantity * entry_price_indicative`. ~20 LoC. Lazy `from iguanatrader.contexts.trading.models import TradeProposal` inside the method body.
- [ ] **1.2** Add private async method `_proposal_created_handler(event: ProposalCreated) -> None`. ~50 LoC body covering: load proposal via `TradeProposalRepository.get_by_id`, missing-row warning + early return, project to `TradeProposalInput`, call `evaluate_proposal`, catch `KillSwitchActiveError` → publish `ProposalRiskEvaluated(outcome="reject", cap_type_breached="kill_switch")`, success path → publish `ProposalRiskEvaluated(outcome=..., cap_type_breached=..., clip_quantity=...)`. Lazy imports for `ProposalCreated`, `ProposalRiskEvaluated`, `TradeProposalRepository`.
- [ ] **1.3** Add public method `register_subscriptions(bus: MessageBus | None = None) -> None`. ~15 LoC. Subscribes `ProposalCreated → self._proposal_created_handler` with `idempotent=True`. Lazy import of `ProposalCreated`.

## 2. Tests (`apps/api/tests/unit/contexts/risk/test_service_bus_bridge.py` NEW)

- [ ] **2.1** Test 1 — happy allow path: stub `TradeProposalRepository.get_by_id` returning a frozen `TradeProposal`, stub `evaluate_proposal` returning `(uuid, Decision(outcome="allow"))`. Invoke handler. Assert `bus.publish` called once with `ProposalRiskEvaluated(outcome="allow")`.
- [ ] **2.2** Test 2 — reject path: same setup; `evaluate_proposal` returns `Decision(outcome="reject", cap_type_breached="daily")`. Assert `ProposalRiskEvaluated(outcome="reject", cap_type_breached="daily")`.
- [ ] **2.3** Test 3 — kill-switch path: `evaluate_proposal` raises `KillSwitchActiveError`. Assert handler swallows + publishes `ProposalRiskEvaluated(outcome="reject", cap_type_breached="kill_switch")`.
- [ ] **2.4** Test 4 — missing-proposal path: `TradeProposalRepository.get_by_id` returns `None`. Assert handler logs warning + publishes nothing.
- [ ] **2.5** Test 5 — `register_subscriptions` integration: construct fresh `MessageBus`, call `register_subscriptions(bus)`, publish `ProposalCreated`, drain queues, assert handler invoked + 1 `ProposalRiskEvaluated` published.

## 3. Daemon wiring (`apps/api/src/iguanatrader/cli/trading.py`)

- [ ] **3.1** Update `_run_daemon` to construct `RiskService` (existing class, takes `repo` + optional `bus`) and call `risk_service.register_subscriptions(bus)` AFTER `trading_service.register_subscriptions()`. ~10 LoC. Remove the K1 line of the `trading.daemon.bus_subscriptions.partial` warning (keep P1 mention).

## 4. Lint + mypy

- [ ] **4.1** Run `python -m ruff check --fix` on modified files (`risk/service.py`, `cli/trading.py`, new test file).
- [ ] **4.2** Run `python -m black` on the same set.
- [ ] **4.3** Run `python -m mypy --strict --no-incremental` on:
  - `apps/api/src/iguanatrader/contexts/risk/service.py`
  - `apps/api/src/iguanatrader/cli/trading.py`
  - `apps/api/tests/unit/contexts/risk/test_service_bus_bridge.py`

## 5. Commit + PR + retro stub

- [ ] **5.1** Branch `slice/k1-followup-bus-subscriptions` → push → open PR.
- [ ] **5.2** PR body: add §4.5 self-review marker block (per ai-playbook v0.11 known-gap workaround).
- [ ] **5.3** Author forward-retro stub `retros/k1-followup-bus-subscriptions.md`.

---

## Estimated effort

| Group | Files | Effort | LoC |
|---|---|---|---|
| 1 RiskService body fills | `risk/service.py` (3 methods) | 1h | ~85 |
| 2 Unit + integration tests | `test_service_bus_bridge.py` (NEW) | 1h | ~150 |
| 3 Daemon wiring | `cli/trading.py` (1 update) | 0.25h | ~10 |
| 4 Lint + mypy | (cleanup pass) | 0.25h | – |
| 5 PR + retro | branch + PR + retro stub | 0.5h | ~50 |

**Total**: ~3h sequential. **Net new LoC**: ~245.

**Blast radius**: zero archive-surface modification — pure additive on `RiskService`. T4's `risk_check_handler` continues to function (now actually receives events instead of zero events). K1's existing `RiskProposalAccepted/Rejected` consumers (audit, observability) untouched.
