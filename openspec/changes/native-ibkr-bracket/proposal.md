## Why

Audit finding **#6** (the one PARTIAL residual after the #283/#285/#289 remediation wave): an approved entry threads its protective `stop_price`/`target_price` onto the order row and the daemon's `stop_hit_sweep` cron enforces the stop on each tick — but the order sent to IBKR is a **naked single order**. If a fill happens and the daemon dies before the next sweep tick, the live position has **no resting stop at the broker**. The robust fix (chosen by the operator) is to transmit a native IBKR bracket so the protective stop rests broker-side, surviving a daemon outage.

## What Changes

- New **feature flag** `IGUANATRADER_NATIVE_BRACKET` (truthy ∈ {1,true,yes,on}, **default OFF**). OFF is byte-identical to today (naked order + cron sweep).
- When ON and an entry carries a protective `stop_price`, `IBKRAdapter.place_order` submits a **native bracket**: parent market entry + child `STP` stop-loss (reverse side, `aux_price=stop_price`) + optional child `LMT` take-profit (`limit_price=target_price`), transmitted **atomically** with `parentId` linkage and an OCA group (a fill on one child cancels the other).
- New broker-port method `IBClient.place_bracket_order(...)`; the production `IbAsyncIBClient` builds the bracket by hand (ib_async's `bracketOrder` helper assumes a limit parent — ours is market): parent `transmit=False` + reserved `orderId`; children carry `parentId`/OCA; the last leg `transmit=True` fires the whole bracket. The in-tree fake records the legs for tests.
- **Protection-model selection (safety):** with the flag ON the daemon does NOT construct/register `stop_hit_sweep` or `trailing_stop_sweep` — the broker holds the stop; running both would double-close the position. With the flag OFF the sweeps are wired exactly as before. The daemon logs the active `protection_model` (`broker_bracket` vs `cron_sweep`).
- **NOT** changing: the flag-OFF behavior, the order/ledger persistence, the kill-switch, or the dual-daemon comms. Native-bracket mode ships a FIXED protective stop (+ optional take-profit); daemon-side trailing tightening is a documented follow-up. Native bracket MUST be validated against IBKR paper before any live enablement.

## Capabilities

### New Capabilities
- `native-ibkr-bracket`: feature-flagged broker-side protective bracket — entry + atomic STP (+ optional LMT take-profit) with parent/OCA linkage — so the stop rests at IBKR and survives a daemon outage; mutually exclusive with the cron stop-sweeps to prevent double-close.

### Modified Capabilities
(none — no archived spec capability changes its requirements)

## Impact

- **Code**: `contexts/trading/brokers/ibkr_adapter.py` (bracket branch + `native_bracket` ctor flag), `brokers/client_protocol.py` (`place_bracket_order` on `IBClient`), `brokers/ib_async_client.py` (real bracket), `cli/trading.py` (`IGUANATRADER_NATIVE_BRACKET`, protection-model gating), `tests/_fakes/ib_async_fake.py`.
- **Hard rules**: keeps "kill-switch obligatorio" + immutable execution logs intact; strengthens position protection. Mutual-exclusion of bracket-vs-sweep prevents a double-sell.
- **Tests**: `tests/unit/contexts/trading/brokers/test_native_bracket.py` — buy/sell bracket shape, stop-only, no-stop fallback, flag-OFF single-order path, idempotency. Full broker+cli suite green (85), ruff clean.
- **Config**: `IGUANATRADER_NATIVE_BRACKET` (default OFF). No secrets, no new dependencies.
- **Operational**: enable only after IBKR-paper validation; ON disables the cron stop-sweeps by design.
