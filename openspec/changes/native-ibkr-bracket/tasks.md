## 1. Broker port + production client

- [x] 1.1 Add `place_bracket_order(contract, parent, stop_loss, take_profit | None) -> str` to the `IBClient` Protocol.
- [x] 1.2 `IbAsyncIBClient.place_bracket_order`: hand-built market-parent bracket — parent `transmit=False` + reserved `orderId`; children carry `parentId`; OCA group + `ocaType=1` when a take-profit exists; the last leg `transmit=True` fires the bracket atomically; wait for the parent `permId` (same reject detection as `place_order`).
- [x] 1.3 In-tree fake records the bracket legs (`placed_brackets`) and returns a synthetic perm_id.

## 2. Adapter bracket path (feature-flagged)

- [x] 2.1 `IBKRAdapter.__init__` gains `native_bracket: bool = False`.
- [x] 2.2 `place_order`: when `native_bracket` AND `stop_price is not None`, build parent + reverse-side `STP` (+ optional `LMT` take-profit) and call `place_bracket_order`; cache + emit `broker.order.bracket_placed`; return the parent id. Otherwise the unchanged single-order path.
- [x] 2.3 Children carry `order_ref` `"{client_order_id}:stop"` / `":tp"`; idempotency cache dedupes a repeat `client_order_id` before any submission.

## 3. Protection-model selection (safety)

- [x] 3.1 `IGUANATRADER_NATIVE_BRACKET` env (truthy ∈ {1,true,yes,on}, default OFF) read in `_build_broker` + passed to the adapter.
- [x] 3.2 When ON, the daemon skips constructing/registering `stop_hit_sweep` + `trailing_stop_sweep` (broker holds the stop; avoids double-close). When OFF the sweeps wire exactly as before. Log the active `protection_model`.
- [x] 3.3 Document that native-bracket mode is a FIXED stop (+ optional TP), no daemon-side trailing (follow-up).

## 4. Validation & gate

- [x] 4.1 Tests: buy bracket (parent MKT + reverse STP + reverse LMT), sell bracket (children BUY), stop-only (no TP), flag-ON no-stop → single path, flag-OFF with stop → single path, idempotent repeat.
- [x] 4.2 Full broker + cli suites green (85); ruff clean on touched files; `openspec validate native-ibkr-bracket --strict` passes.
- [ ] 4.3 **Operational gate (not code):** validate the bracket against IBKR paper (entry fills → resting STP visible in TWS; child OCA cancels correctly) BEFORE enabling the flag in any live deploy.
