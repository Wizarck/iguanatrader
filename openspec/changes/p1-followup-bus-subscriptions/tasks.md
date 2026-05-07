# tasks — p1-followup-bus-subscriptions

> Order: 1 → 2 → 3 → 4 → 5. Each group has 1-3 sub-tasks. Slot reservations per [.ai-playbook/specs/migration-slot-reservation.md](../../../.ai-playbook/specs/migration-slot-reservation.md): no migrations claimed; pure additive code.
>
> Pattern usage: this slice is the **second canonical instance** of the "bus-bridge follow-up" pattern (K1-followup PR #103 was the first). Two recurrences justify promoting the pattern to ai-playbook v0.11.1 as a named pattern post-merge.

## 1. ApprovalService body fills (`apps/api/src/iguanatrader/contexts/approval/service.py`)

- [ ] **1.1** Add module-level helpers `_parse_approval_channels(raw: str | None) -> list[str]` and `_parse_approval_timeout(raw: str | None) -> int`. ~25 LoC. Patterns: `_parse_approval_channels` = CSV split + strip + lowercase + `[]` filter (default `"telegram,dashboard"`); `_parse_approval_timeout` = `int()` parse + clamp `[1, 86400]` (default `300`). Colocate above the `ApprovalService` class — same shape as T4's `_parse_watchlist`.
- [ ] **1.2** Add public method `register_subscriptions(bus: MessageBus | None = None) -> None`. ~35 LoC. Subscribes 4 events with `idempotent=True`: `trading.ApprovalRequested → self._approval_requested_handler`, `approval.ApprovalProposalApproved → self._bridge_to_trading_approved_handler`, `approval.ApprovalProposalRejected → self._bridge_to_trading_rejected_handler`, `approval.ApprovalProposalTimedOut → self._bridge_to_trading_timeout_handler`. Lazy imports for the 4 event classes. Raise `RuntimeError` if both `bus` arg and `self._message_bus` are None.
- [ ] **1.3** Add private async method `_approval_requested_handler(event: ApprovalRequested) -> None`. ~25 LoC body covering: read 2 env-vars via the §1.1 helpers, call `await self.create_request(proposal_id=event.proposal_id, channels=..., timeout_seconds=...)`, log `approval.bus.request_persisted` with `proposal_id`, `request_id` (from returned row), `channels`, `timeout_seconds`. No exception swallowing (re-raise to bus retry).
- [ ] **1.4** Add 3 private async bridge handlers — `_bridge_to_trading_approved_handler`, `_bridge_to_trading_rejected_handler`, `_bridge_to_trading_timeout_handler`. ~50 LoC total (~17 each). Each: resolve `tenant_id` from `tenant_id_var.get()`, log+return early if `None` (`approval.bus.bridge_skipped_no_tenant` ERROR), construct trading-flavored event (`ProposalApproved` / `ProposalRejected`), `await self._message_bus.publish(event)`, log `approval.bus.translated_to_trading_{approved,rejected,timed_out}`. Lazy import of `iguanatrader.contexts.trading.events` inside each handler. Timeout handler emits `ProposalRejected(reason="approval_timeout")` (sentinel literal).

## 2. Tests (`apps/api/tests/unit/contexts/approval/test_service_bus_bridge.py` NEW)

- [ ] **2.1** Test 1 (inbound, env-set) — `test_inbound_handler_creates_request_row_with_env_defaults`. Monkeypatch `IGUANATRADER_DEFAULT_APPROVAL_CHANNELS="telegram"` + `IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS="600"`. Mock `repository.create_request` (AsyncMock). Invoke handler. Assert `create_request` called exactly once with `(proposal_id, ["telegram"], 600)`.
- [ ] **2.2** Test 2 (inbound, env-unset) — `test_inbound_handler_uses_default_channels_when_env_unset`. Both env-vars unset. Assert `create_request` called with `["telegram", "dashboard"]` + `timeout_seconds=300`.
- [ ] **2.3** Test 3 (clamp) — `test_inbound_handler_clamps_timeout_to_valid_range`. Env `TIMEOUT="999999"` → clamp to `86400`. Env `TIMEOUT="0"` → clamp to `1`.
- [ ] **2.4** Test 4 (outbound approved) — `test_outbound_bridge_translates_approved_to_trading_event`. Set `tenant_id_var` via fixture. Subscribe a `_capture` to `trading.ProposalApproved`. Invoke `_bridge_to_trading_approved_handler` directly. Drain queues. Assert exactly 1 captured event with same `proposal_id`, `decision_id`, resolved `tenant_id`, `decided_via_channel`.
- [ ] **2.5** Test 5 (outbound rejected) — `test_outbound_bridge_translates_rejected_to_trading_event`. Same shape but for `ApprovalProposalRejected(reason="user_declined")`. Assert `trading.ProposalRejected(reason="user_declined")`.
- [ ] **2.6** Test 6 (outbound timeout sentinel) — `test_outbound_bridge_translates_timeout_to_trading_rejected_with_sentinel`. Invoke timeout handler. Assert `trading.ProposalRejected(reason="approval_timeout")`.
- [ ] **2.7** Test 7 (ContextVar fallback) — `test_outbound_bridge_skips_when_tenant_context_unset`. Reset `tenant_id_var`. Subscribe `_capture` to `trading.ProposalApproved`. Invoke `_bridge_to_trading_approved_handler`. Assert nothing captured + ERROR log line `approval.bus.bridge_skipped_no_tenant` emitted (use `caplog`).
- [ ] **2.8** Test 8 (integration, all 4 wires) — `test_register_subscriptions_wires_all_four_handlers`. Construct fresh bus + service + tenant_id_var. Call `register_subscriptions(bus)`. Publish each of the 4 inbound events in sequence. Drain queues. Assert: `repository.create_request` called once + exactly 1 `trading.ProposalApproved` + 2 `trading.ProposalRejected` (one from rejected, one from timeout) captured. `await bus.aclose()` at end.

## 3. Daemon wiring (`apps/api/src/iguanatrader/cli/trading.py`)

- [ ] **3.1** Update `_run_daemon` to construct `ApprovalService(repository=ApprovalRepository(), message_bus=bus)` AFTER `risk_service.register_subscriptions(bus)` and call `approval_service.register_subscriptions(bus)`. ~10 LoC. Lazy imports at function-body scope (no top-level imports — gotcha #29 + --help perf).
- [ ] **3.2** Remove the entire `log.warning("trading.daemon.bus_subscriptions.partial", ...)` block (lines 171-178 currently). Replace with single line `log.info("trading.daemon.bus_subscriptions.complete")` and one comment line above it documenting that K1+P1 hops are both closed (point to PRs #103 + this PR for the audit trail).

## 4. Lint + mypy

- [ ] **4.1** Run `python -m ruff check --fix` on modified files (`approval/service.py`, `cli/trading.py`, new test file).
- [ ] **4.2** Run `python -m black` on the same set.
- [ ] **4.3** Run `python -m mypy --strict --no-incremental` on:
  - `apps/api/src/iguanatrader/contexts/approval/service.py`
  - `apps/api/src/iguanatrader/cli/trading.py`
  - `apps/api/tests/unit/contexts/approval/test_service_bus_bridge.py`

## 5. Commit + PR + retro stub

- [ ] **5.1** Branch `slice/p1-followup-bus-subscriptions` → push → open PR.
- [ ] **5.2** PR body: add §4.5 self-review marker block (per ai-playbook v0.11 known-gap workaround).
- [ ] **5.3** Author forward-retro stub `retros/p1-followup-bus-subscriptions.md` — pre-flag candidates: pattern recurrence-2 confirms playbook promotion; ContextVar fallback test was the new test-design wrinkle vs K1-followup; daemon log message change is the only operator-visible diff.

---

## Estimated effort

| Group | Files | Effort | LoC |
|---|---|---|---|
| 1 ApprovalService body fills | `approval/service.py` (2 helpers + 5 methods) | 1.25h | ~135 |
| 2 Unit + integration tests | `test_service_bus_bridge.py` (NEW) | 1.25h | ~210 |
| 3 Daemon wiring | `cli/trading.py` (1 update + log change) | 0.25h | ~12 |
| 4 Lint + mypy | (cleanup pass) | 0.25h | – |
| 5 PR + retro | branch + PR + retro stub | 0.5h | ~60 |

**Total**: ~3.5h sequential. **Net new LoC**: ~415 (approx. 145 src + 210 tests + 60 retro/openspec docs).

**Blast radius**: zero archive-surface modification — pure additive on `ApprovalService`. P1's existing `ApprovalProposalApproved/Rejected/TimedOut` consumers (audit log, dashboard SSE, observability) continue to fire byte-for-byte. T4's `execute_on_approval_handler` + `proposal_rejected_handler` already exist and consume the trading-flavored events emitted by the bridge — no T4 modification.

**Carry-forward** (next slice): T4-followup integration test now possible end-to-end — full `propose → risk → approve → execute` chain runnable in a single test. Strategy resolver production wiring (`_make_strategy_resolver` `NotImplementedError` placeholder in `cli/trading.py`) also lands in T4-followup.
