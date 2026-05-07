# Design — k1-followup-bus-subscriptions

> **Purpose**: close the propose→risk hop in T1's archived event pipeline. Add additive `register_subscriptions(bus)` to `RiskService` that bridges T1's `ProposalCreated` event into K1's `evaluate_proposal` engine call, then re-emits the outcome on T1's expected `ProposalRiskEvaluated` event class.
>
> **Pattern reference**: this slice is the canonical "**bus-bridge follow-up**" example — additive wiring on an already-archived service that completes a previously-broken event chain. Promote to ai-playbook v0.11.1 as a named pattern if it recurs.

## 1. Pipeline context

```
T1 propose path                   K1 (THIS SLICE WIRES)               T4 risk_check_handler
─────────────────                 ───────────────────────              ──────────────────────
TradingService.propose
  └─▶ insert TradeProposal
  └─▶ publish ProposalCreated ───▶ RiskService.register_subscriptions
                                     subscribes (idempotent=True)
                                     │
                                     ▼
                                  _proposal_created_handler(event)
                                     ├─ load TradeProposal by id
                                     ├─ project → TradeProposalInput
                                     ├─ call evaluate_proposal(...)
                                     │     emits K1-native events
                                     │     (RiskProposalAccepted /
                                     │      RiskProposalRejected) — UNCHANGED
                                     │
                                     └─ ALSO publish ProposalRiskEvaluated
                                        (T1's class, T4's expected) ────▶ TradingService.risk_check_handler
                                                                            on allow|clip → ApprovalRequested
                                                                            on reject     → ProposalRejected
```

**Critical invariant**: K1's existing publish path (`RiskProposalAccepted` / `RiskProposalRejected`) is UNTOUCHED. Whatever subscribers existed continue to work. The new emission is purely additive.

## 2. Per-component specifications

### 2.1 `RiskService.register_subscriptions(bus: MessageBus) -> None`

**File**: `apps/api/src/iguanatrader/contexts/risk/service.py` (NEW method on existing `RiskService` class)

```python
def register_subscriptions(self, bus: MessageBus | None = None) -> None:
    """Subscribe to trading.ProposalCreated and bridge to evaluate_proposal.

    Idempotent at the bus boundary (slice 2 D1: subscribe with
    ``idempotent=True``). Re-registering creates a new subscription
    handle — the daemon calls this once per service instance on
    startup; tests construct fresh services per test.
    """
    target_bus = bus if bus is not None else self._bus
    from iguanatrader.contexts.trading.events import ProposalCreated

    target_bus.subscribe(
        ProposalCreated,
        self._proposal_created_handler,
        idempotent=True,
    )
```

**Notes**:
- `RiskService.__init__` already takes a `MessageBus | None`. Reuses it.
- The trading event import is **lazy** (inside the method body) to keep K1's import surface free of trading-context dependencies at module-load time. Service layer ALREADY imports trading types in other contexts; the lazy-import keeps this slice's blast radius minimal.

### 2.2 `_proposal_created_handler(event: ProposalCreated) -> None`

**File**: same file, NEW private async method.

```python
async def _proposal_created_handler(self, event: "ProposalCreated") -> None:
    """Bridge handler: ProposalCreated → evaluate_proposal → ProposalRiskEvaluated.

    Slice K1-followup §2.B body. Loads the TradeProposal row,
    projects to TradeProposalInput, calls evaluate_proposal (which
    emits K1-native events), then publishes ProposalRiskEvaluated
    so T1 TradingService.risk_check_handler can react.

    Failure modes:
    - Missing TradeProposal row → log warning, publish nothing (the
      bus's publish-failed events would have already fired).
    - KillSwitchActiveError from evaluate_proposal → log + publish
      ProposalRiskEvaluated(outcome="reject", cap_type_breached=
      "kill_switch") so T4 still drives the proposal to terminal state.
    - Generic exception → re-raise (bus catches at the boundary, logs
      + suppresses; the proposal is left in an "in-flight" limbo for
      operator inspection).
    """
    from iguanatrader.contexts.trading.events import ProposalRiskEvaluated
    from iguanatrader.contexts.trading.models import TradeProposal
    from iguanatrader.contexts.trading.repository import TradeProposalRepository

    proposal_row = await TradeProposalRepository().get_by_id(event.proposal_id)
    if proposal_row is None:
        log.warning(
            "risk.bridge.proposal_missing",
            proposal_id=str(event.proposal_id),
        )
        return

    proposal_input = self._project_proposal_input(proposal_row)
    try:
        evaluation_id, decision = await self.evaluate_proposal(proposal_input)
    except KillSwitchActiveError:
        await self._bus.publish(
            ProposalRiskEvaluated(
                tenant_id=event.tenant_id,
                proposal_id=event.proposal_id,
                outcome="reject",
                cap_type_breached="kill_switch",
            )
        )
        return

    # Bridge: emit T1's expected event shape from K1's Decision.
    await self._bus.publish(
        ProposalRiskEvaluated(
            tenant_id=event.tenant_id,
            proposal_id=event.proposal_id,
            outcome=decision.outcome,  # "allow" | "clip" | "reject"
            cap_type_breached=decision.cap_type_breached,
            clip_quantity=decision.clip_quantity,
        )
    )
```

### 2.3 `_project_proposal_input(row: TradeProposal) -> TradeProposalInput`

**File**: same file, NEW static method.

```python
@staticmethod
def _project_proposal_input(row: "TradeProposal") -> TradeProposalInput:
    """Project TradeProposal ORM row → K1's TradeProposalInput DTO.

    Service-layer single conversion point per K1 design D2 (engine
    stays free of T1's ORM types). ``notional_value`` is computed
    here as quantity * entry_price_indicative.
    """
    return TradeProposalInput(
        id=row.id,
        tenant_id=row.tenant_id,
        notional_value=Decimal(str(row.quantity)) * Decimal(str(row.entry_price_indicative)),
        side=row.side,  # type: ignore[arg-type]  # validated by ORM check constraint
    )
```

## 3. Anti-patterns explicitly rejected

- **Renaming K1's events to use T1's `ProposalRiskEvaluated`** — would touch K1's archived surface; existing K1-native subscribers (audit context, observability) would break. Additive emission preserves both consumer sets.
- **Dropping K1's `RiskProposalAccepted` / `RiskProposalRejected` events** — same archive-surface argument.
- **Mutating `TradeProposal` state** — append-only table per slice T1; T4 already established the "rejection-is-event-only" pattern. K1 follows.
- **Polling for new proposals via a timer** — bus-driven only. The whole point of the in-process bus is to remove polling.
- **Direct call from `TradingService.propose` to `RiskService.evaluate_proposal`** — would couple T1 to K1 at module-import time. The bus boundary is canonical.

## 4. Tests plan

`apps/api/tests/unit/contexts/risk/test_service_bus_bridge.py` (NEW), 4 unit tests:

- **2.A.1 happy allow path**: stub `TradeProposalRepository.get_by_id` to return a frozen `TradeProposal` row. Stub `evaluate_proposal` to return `(uuid, Decision(outcome="allow"))`. Trigger `_proposal_created_handler(ProposalCreated(...))`. Assert: `bus.publish` called once with `ProposalRiskEvaluated(outcome="allow")`.
- **2.A.2 reject path**: same setup; `evaluate_proposal` returns `Decision(outcome="reject", cap_type_breached="daily")`. Assert: `ProposalRiskEvaluated(outcome="reject", cap_type_breached="daily")`.
- **2.A.3 kill-switch path**: `evaluate_proposal` raises `KillSwitchActiveError`. Assert: handler swallows, publishes `ProposalRiskEvaluated(outcome="reject", cap_type_breached="kill_switch")`.
- **2.A.4 missing-proposal path**: `TradeProposalRepository.get_by_id` returns `None`. Assert: handler logs warning, publishes NOTHING.

Plus 1 integration-style test for `register_subscriptions`:

- **2.B.1**: construct fresh `MessageBus`, call `RiskService.register_subscriptions(bus)`, then `bus.publish(ProposalCreated(...))`, drain queues, assert handler invoked + 1 `ProposalRiskEvaluated` published.

Total: 5 tests, ~150 LoC.

## 5. Acceptance gates

- All 5 unit + integration tests pass.
- mypy --strict + ruff + black clean across modified files.
- T4 `TradingService.risk_check_handler` continues to consume `ProposalRiskEvaluated` correctly (smoke check via `pytest --collect-only` of T1's existing tests; no behaviour change there).
- Daemon boots with the new wiring: `iguanatrader trading run --mode paper --tenant test` no longer logs the `trading.daemon.bus_subscriptions.partial` warning for K1 (only P1 remains until P1-followup).

## 6. Interaction with prior + future slices

- **Closes T4-followup item #1** (K1 register_subscriptions). T4-followup integration test can now exercise the propose→risk hop end-to-end.
- **Does NOT close P1** (their own follow-up).
- **Does NOT touch K1's archived surface** beyond the additive 2 methods + 1 helper. Zero risk to existing K1 callers.

## 7. Open questions

(none — slice is mechanical bridge wiring; no design ambiguity)
