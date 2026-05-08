# Retrospective: ibkr-adapter-resilient (slice T2)

- **Archived**: 2026-05-08 (post-hoc; PR merged 2026-05-06)
- **PR**: [#88](https://github.com/Wizarck/iguanatrader/pull/88)
- **Squash SHA**: `106e52e`
- **Archive path**: `openspec/changes/archive/2026-05-06-ibkr-adapter-resilient/`
- **Schema**: spec-driven
- **Tasks**: 100% (code shipped + consumed by T4 + deployment-foundation 3.B.2 wiring + T4-followup-market-data ingestor sharing)

## What worked

- **`HeartbeatMixin` + canonical backoff `[3, 6, 12, 24, 48]`** from slice 2 (`shared-primitives`) integrated cleanly — IBKRAdapter's reconnect loop was a 1-screen implementation.
- **Idempotency keyed by `client_order_id`** at the adapter layer prevented a class of "double submit on retry" bugs that would have been catastrophic in live mode.
- **`ib_async` (MIT-licensed fork of ib-insync)** chosen over the deprecated `ib-insync`; survives indefinitely without forking.
- **Reconciliation-on-reconnect via `client.reqAllOpenOrders()`** (rather than session-scoped `client.openOrders()`) catches the TWS-restart-mid-session edge case.
- **Test fakes via in-tree `client_protocol.IBClient` Protocol + InTreeFake**: TWS Gateway never required in CI; the resilience contract is exercised deterministically.

## What didn't

- **Post-hoc archive only** (this entry is the archive itself, written 2 days after merge). Same silent-drift pattern as the Wave 2 archive sweep + later closed by ai-playbook v0.10.2 propagate-archive.yml workflow.

## Lessons

- The Protocol+InTreeFake+DeferredProductionInstall pattern from ai-playbook v0.11 was first piloted here (T2 ships fakes; deployment-foundation 3.B.2 ships the production wiring via `build_ib_async_client_from_env()`). Confirms the pattern.
- Adapter-level idempotency (vs service-level) is the right boundary: the retry surface lives where network failures happen.

## Carry-forward (closed downstream)

- ✅ Deployment-foundation 3.B.2 wired `IbAsyncIBClient` into `IBKRAdapter` via composition root.
- ✅ T4-followup-market-data shares the same `IbAsyncIBClient` instance with the IBKR ingestor (1 socket per daemon process; cron schedule prevents temporal overlap).
- (Future) Live-mode integration test against IBKR Gateway in a manual-only CI lane — paper-mode stays in-tree-fake-driven.
