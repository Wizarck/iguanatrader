# Design — p1-followup-bus-subscriptions

> **Purpose**: close the approval→execute hop in T1's archived event pipeline. Add additive `register_subscriptions(bus)` to `ApprovalService` that (1) bridges T1's `ApprovalRequested` event into P1's `create_request` audit-write and (2) translates P1's outcome events (`ApprovalProposalApproved/Rejected/TimedOut`) into T1's expected `trading.ProposalApproved` / `trading.ProposalRejected` events that T4's daemon already consumes.
>
> **Pattern reference**: this is the **second canonical instance** of the "bus-bridge follow-up" pattern — K1-followup (PR #103, merged 2026-05-07) was the first. Two recurrences justify promoting the pattern to ai-playbook v0.11.1 as a named pattern post-merge.

## 1. Pipeline context

```
T4 risk_check_handler            P1 (THIS SLICE WIRES)                  T4 execute_on_approval_handler
──────────────────────            ────────────────────────                ────────────────────────────────
risk_check_handler
  on allow|clip
  └─▶ publish ApprovalRequested ─▶ ApprovalService.register_subscriptions
                                     subscribes (idempotent=True)
                                     │
                                     ▼
                                  _approval_requested_handler(event)
                                     ├─ read DEFAULT_CHANNELS env (CSV)
                                     ├─ read DEFAULT_TIMEOUT env (int)
                                     └─ call self.create_request(
                                          proposal_id=event.proposal_id,
                                          channels=...,
                                          timeout_seconds=...,
                                       )
                                          INSERT approval_requests row
                                          log "approval.request.created"

[Operator decides via dashboard SSE click → POST /approvals/{id}/{approve,reject}
  OR via timeout sweeper after expires_at elapses]
                                     │
                                     ▼
                                  ApprovalService.record_decision (existing)
                                     └─ publish ApprovalProposalApproved
                                        / ApprovalProposalRejected
                                        / ApprovalProposalTimedOut ─────▶ register_subscriptions ALSO
                                                                          subscribed to these (bridge):
                                                                          │
                                                                          ▼
                                                                       _bridge_to_trading_approved_handler
                                                                       _bridge_to_trading_rejected_handler
                                                                          │
                                                                          ▼
                                                                       publish trading.ProposalApproved
                                                                       publish trading.ProposalRejected
                                                                                   │
                                                                                   ▼
                                                                       TradingService.execute_on_approval_handler
                                                                       TradingService.proposal_rejected_handler
                                                                                   │
                                                                                   ▼
                                                                              broker.place_order
```

**Critical invariant**: P1's existing publish path (`ApprovalProposalApproved/Rejected/TimedOut`) is UNTOUCHED. The dashboard SSE stream + audit log + observability subscribers all keep firing byte-for-byte unchanged. The new emissions are purely additive — they ride the SAME publication via additional bridge subscribers.

## 2. Per-component specifications

### 2.1 `ApprovalService.register_subscriptions(bus: MessageBus | None = None) -> None`

**File**: `apps/api/src/iguanatrader/contexts/approval/service.py` (NEW method on existing `ApprovalService` class).

```python
def register_subscriptions(self, bus: MessageBus | None = None) -> None:
    """Wire bus subscriptions: inbound (ApprovalRequested) + outbound bridge.

    Idempotent at the bus boundary (slice 2 D1: subscribe with
    ``idempotent=True``). Re-registering creates new subscription
    handles — the daemon calls this once per service instance on
    startup; tests construct fresh services per test.
    """
    target_bus = bus if bus is not None else self._message_bus
    if target_bus is None:
        raise RuntimeError(
            "ApprovalService.register_subscriptions requires a MessageBus "
            "via constructor injection or method arg."
        )

    # Lazy imports per gotcha #29 (cross-context type isolation +
    # --help performance on the operator CLI).
    from iguanatrader.contexts.approval.events import (
        ApprovalProposalApproved,
        ApprovalProposalRejected,
        ApprovalProposalTimedOut,
    )
    from iguanatrader.contexts.trading.events import ApprovalRequested

    target_bus.subscribe(
        ApprovalRequested,
        self._approval_requested_handler,
        idempotent=True,
    )
    target_bus.subscribe(
        ApprovalProposalApproved,
        self._bridge_to_trading_approved_handler,
        idempotent=True,
    )
    target_bus.subscribe(
        ApprovalProposalRejected,
        self._bridge_to_trading_rejected_handler,
        idempotent=True,
    )
    target_bus.subscribe(
        ApprovalProposalTimedOut,
        self._bridge_to_trading_timeout_handler,
        idempotent=True,
    )
```

**Notes**:
- `ApprovalService.__init__` already takes `message_bus: MessageBus` (required, non-Optional in P1 archive). The method signature accepts `bus: MessageBus | None` for parity with K1-followup's signature; both branches reach a non-None bus or raise.
- All four subscriptions use `idempotent=True` (slice 2 D1) so re-registration on daemon restart is safe.

### 2.2 `_approval_requested_handler(event: ApprovalRequested) -> None`

**Behavior**:
1. Read `IGUANATRADER_DEFAULT_APPROVAL_CHANNELS` (CSV, default `"telegram,dashboard"`) — split + strip + lowercase.
2. Read `IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS` (int, default `300`) — parse, clamp to `[1, 86400]` (1s … 24h).
3. Call `await self.create_request(proposal_id=event.proposal_id, channels=..., timeout_seconds=...)`.
4. Log `approval.bus.request_persisted` with `proposal_id`, `request_id`, `channels`, `timeout_seconds`.

**Edge cases**:
- **DB row already exists**: `create_request` does NOT have a uniqueness constraint on `proposal_id` (an approval_request can be re-issued; sweep_expired creates a timeout decision, then a re-propose path could create a fresh request). The bus subscription is `idempotent=True` so accidental double-publish is filtered by the bus, but a deliberate re-publish (different `idempotency_key`) would create a duplicate row — out of scope, T4 ApprovalRequested publishes once per risk_check_handler invocation per `(tenant, proposal_id)`.
- **Error in `create_request`** (e.g. DB connection lost, tenant context missing): re-raise — the bus catches, logs, and the handler is retried per slice 2 retry policy (or dropped, per the bus's failure-mode contract). Do NOT swallow; an audit-write that silently fails would be worse than a noisy retry.

### 2.3 `_bridge_to_trading_approved_handler(event: ApprovalProposalApproved) -> None`

**Behavior**:
1. Resolve `tenant_id` from `tenant_id_var` ContextVar (the daemon sets this once per tenant-loop in slice T4 §3.4 bootstrap; in tests, the fixture sets it).
2. Construct `trading.ProposalApproved(tenant_id=..., proposal_id=event.proposal_id, decision_id=event.decision_id, decided_at=event.decided_at, decided_via_channel=event.decided_via_channel)`.
3. `await self._message_bus.publish(translated_event)`.
4. Log `approval.bus.translated_to_trading_approved` with `proposal_id`, `decision_id`, `decided_via_channel`.

**Tenant-id resolution**: P1 events do not carry `tenant_id` (P1 was scoped per-tenant via row-level scoping; the event carried `proposal_id` + `decision_id` only, leaving tenant inference to the consumer's session context). The bridge resolves it from the ContextVar — consistent with the slice-2 D2 contract that domain code reads tenant from the ContextVar, not from event payloads.

**ContextVar fallback**: if `tenant_id_var.get()` returns `None` (test running outside a request scope or bootstrap not yet wired), the bridge logs a `ERROR approval.bus.bridge_skipped_no_tenant` and returns without publishing. T4's downstream consumer would otherwise fail when `tenant_listener` rejects the cross-tenant write. Tests must set the ContextVar.

### 2.4 `_bridge_to_trading_rejected_handler(event: ApprovalProposalRejected) -> None`

**Behavior**: identical pattern to 2.3 but emits `trading.ProposalRejected(tenant_id=..., proposal_id=event.proposal_id, reason=event.reason or "user_declined")`. T4's `proposal_rejected_handler` already exists and consumes `ProposalRejected` (idempotent subscriber).

### 2.5 `_bridge_to_trading_timeout_handler(event: ApprovalProposalTimedOut) -> None`

**Behavior**: identical pattern; emits `trading.ProposalRejected(tenant_id=..., proposal_id=event.proposal_id, reason="approval_timeout")`. The `reason` literal is the canonical sentinel — consumers can grep on it for alerting.

**Why collapse timeout → ProposalRejected?** T4's daemon already has exactly one terminal handler for the rejected path (`proposal_rejected_handler`). Adding a separate `ProposalApprovalTimedOut` event class on the trading side would require modifying the T4 archive (its `register_subscriptions` would need a new wire) — that violates the "zero archive-surface modification" invariant. The reason-string sentinel preserves observability without an event-class proliferation.

### 2.6 Daemon wiring (`apps/api/src/iguanatrader/cli/trading.py`)

Insert after the existing `risk_service.register_subscriptions(bus)` call:

```python
from iguanatrader.contexts.approval.repository import ApprovalRepository
from iguanatrader.contexts.approval.service import ApprovalService

approval_service = ApprovalService(
    repository=ApprovalRepository(),
    message_bus=bus,
)
approval_service.register_subscriptions(bus)
```

Note: `ApprovalRepository` reads `session_var` lazily (no constructor session arg, unlike `RiskRepository` — confirmed by reading repository.py lines 1-80 + base class).

**Remove** the entire `log.warning("trading.daemon.bus_subscriptions.partial", ...)` block — the partial scope is now fully closed. Replace with a single `log.info("trading.daemon.bus_subscriptions.complete")` line.

### 2.7 Environment variables

Both new env-vars follow slice T4 §3.3.g pattern (env-var-first-cut; v2 SaaS swaps to a per-tenant table):

| Var | Type | Default | Notes |
|---|---|---|---|
| `IGUANATRADER_DEFAULT_APPROVAL_CHANNELS` | CSV string | `"telegram,dashboard"` | Channels for `create_request.delivered_to_channels`. Validated against P1 `ChannelKind` Literal at parse time. |
| `IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS` | int | `300` (5 min) | Clamped `[1, 86400]`. |

Both read at handler-call time (not at daemon-boot time) so an operator can `kubectl set env` + restart pod without redeploying. Add a `_parse_approval_channels` + `_parse_approval_timeout` helper pair colocated in `service.py` (private module-level functions, not class members — same shape as T4's `_parse_watchlist`).

## 3. Anti-patterns to avoid

1. **Do NOT modify P1's `_publish_event`** to also emit trading-flavored events. That would couple two contexts inside the audit-write path and rotate the archive surface. The bridge handlers are external-additive.
2. **Do NOT add `tenant_id` to P1 events**. Modifying the archived `ApprovalProposalApproved/Rejected/TimedOut` dataclasses changes their on-the-wire shape — risky for any in-flight consumers (audit log, dashboard SSE) whose schemas are derived from them. Resolve from ContextVar instead.
3. **Do NOT introduce a new `ProposalApprovalTimedOut` event on the trading side**. T4 has a single `proposal_rejected_handler`; collapsing timeout → `ProposalRejected(reason="approval_timeout")` keeps T4's archive untouched.
4. **Do NOT make the bridge handlers swallow exceptions**. If publish fails, the bus's failure-mode contract handles it (slice 2 D8). Swallowing would hide a real broker-disconnected scenario.
5. **Do NOT make `_approval_requested_handler` perform channel push** (Telegram bot send, Hermes HTTP). That's the deliberately-deferred `P1-followup-channel-fanout` slice. Channel adapters are constructed by their own bootstraps + injected — out of scope here.

## 4. Tests

**File**: `apps/api/tests/unit/contexts/approval/test_service_bus_bridge.py` (NEW)

| # | Test | Scenario | Asserts |
|---|---|---|---|
| 4.1 | `test_inbound_handler_creates_request_row_with_env_defaults` | publish `ApprovalRequested` with monkeypatched env-vars `CHANNELS="telegram"`, `TIMEOUT=600` | exactly 1 call to `repository.create_request(proposal_id, ["telegram"], 600)` |
| 4.2 | `test_inbound_handler_uses_default_channels_when_env_unset` | env-vars unset | `create_request` called with `["telegram", "dashboard"]` + `timeout_seconds=300` |
| 4.3 | `test_inbound_handler_clamps_timeout_to_valid_range` | env `TIMEOUT=999999` | clamped to `86400` |
| 4.4 | `test_outbound_bridge_translates_approved_to_trading_event` | publish `ApprovalProposalApproved`, ContextVar tenant set | exactly 1 `trading.ProposalApproved` published with same `proposal_id`, `decision_id`, resolved `tenant_id` |
| 4.5 | `test_outbound_bridge_translates_rejected_to_trading_event` | publish `ApprovalProposalRejected(reason="user_declined")` | `trading.ProposalRejected(reason="user_declined")` |
| 4.6 | `test_outbound_bridge_translates_timeout_to_trading_rejected_with_sentinel` | publish `ApprovalProposalTimedOut` | `trading.ProposalRejected(reason="approval_timeout")` |
| 4.7 | `test_outbound_bridge_skips_when_tenant_context_unset` | publish `ApprovalProposalApproved`, tenant_id_var unset | no `trading.ProposalApproved` published; ERROR log line `approval.bus.bridge_skipped_no_tenant` emitted |
| 4.8 | `test_register_subscriptions_wires_all_four_handlers` | construct fresh bus + service, call `register_subscriptions`, publish all 4 inbound events in sequence | `repository.create_request` called once + 3 `trading.*` events published once each |

Tests use `pytest.MonkeyPatch` for env-vars + `tenant_id_var` setup. `repository` is `AsyncMock`. Bus is a real `MessageBus` (drained by yielding to the event loop, same shape as K1-followup tests).

## 5. Acceptance criteria

Code-level (verifiable by tests + CI):

1. `ApprovalService(repository, message_bus).register_subscriptions(bus)` registers exactly 4 subscriptions on the bus (no more, no less).
2. All 8 unit tests in §4 pass.
3. `mypy --strict --no-incremental` passes on `apps/api/src/iguanatrader/contexts/approval/service.py`, `apps/api/src/iguanatrader/cli/trading.py`, `apps/api/tests/unit/contexts/approval/test_service_bus_bridge.py`.
4. `ruff check` + `black --check` pass on the same set.

Operator-driven (verified post-merge):

5. Daemon boot log emits `trading.daemon.bus_subscriptions.complete` (no `partial` warning).
6. Manual proposal creation in paper mode → bus emits chain `ProposalCreated → ProposalRiskEvaluated → ApprovalRequested → ApprovalRequest row INSERTed → operator clicks dashboard → POST /approvals/{id}/approve → ApprovalProposalApproved → trading.ProposalApproved → broker.place_order`.

## 6. Cross-context interaction

- **Reads**: `tenant_id_var` ContextVar (slice 2 D2). No DB reads beyond what `create_request` already does.
- **Writes**: 1 INSERT into `approval_requests` per `ApprovalRequested` event (via existing `create_request`). No schema changes; no migration claimed (per migration-slot-reservation.md).
- **Bus emissions**: 4 new emissions of `trading.ProposalApproved` / `trading.ProposalRejected` per inbound P1 event. T4's existing handlers consume them; this slice does not modify T4.
- **Imports**: lazy across the approval/trading boundary (gotcha #29). Direct imports at module top would create a circular ref (trading already imports approval/events.py for SSE).

## 7. Open questions

None at design time. The retro-from-K1-followup pre-flagged two pre-flight greps (CapType literals + KillSwitchActiveError import path); equivalent pre-flight for P1-followup is unnecessary because (a) `ApprovalProposalApproved/Rejected/TimedOut` are well-typed dataclasses with no Literal subtleties, (b) the trading-side `ProposalApproved/Rejected` constructors were verified during K1-followup work.
