# Tasks: dual-daemon-mode-toggle-and-reconcile

Execute in order. Each task is a discrete, testable unit. Mark `[x]` as completed during `/opsx:apply`.

## Phase 1 — DB + backend foundation

- [x] 1. **Migration `0026_tenant_trading_modes.py`** (renumbered from `0020` — `0020`-`0025` were already taken post-spec) — create table per proposal §2. Seed all existing tenants with `(paper, enabled=true)` + `(live, enabled=false)`. Test forward + downgrade.
- [x] 2. **Migration `0027_daemon_heartbeats.py`** (renumbered from `0021`) — create table `daemon_heartbeats(tenant_id, mode, last_heartbeat_at, ib_connected)` with `PRIMARY KEY (tenant_id, mode)`. No seed (rows created on first heartbeat write).
- [x] 3. **`apps/api/src/iguanatrader/contexts/trading/models.py`** — add `TenantTradingMode` + `DaemonHeartbeat` SQLAlchemy models matching migrations 0026/0027.
- [x] 4. **`apps/api/src/iguanatrader/contexts/trading/repository.py`** — add `TradingModeRepository` with methods: `load_trading_enabled(tenant_id, mode) -> bool`, `set_trading_enabled(tenant_id, mode, enabled, user_id, reason) -> TenantTradingMode`, `write_heartbeat(tenant_id, mode, ib_connected) -> None`, `load_daemon_status_summary(tenant_id) -> list[DaemonStatusRow]` (joins heartbeats + last fill + pending count). Row dataclass `DaemonStatusRow` is the persistence-layer mirror of the Pydantic `DaemonStatusOut` DTO (task 15).

## Phase 1.5 — TradeProposal state column (unblocker for Phase 2 drain + Task 4 pending count)

Discovered during Task 4 that the spec's `pending_proposals_count` query + the Phase 2 drain semantic both depend on a `TradeProposal.state` column that the codebase did not have (rejection was tracked exclusively via `approval_decisions` events). Operator chose **Option B** (denormalise state onto the entity, matching the spec verbatim) over Option A (count via JOIN against `approval_decisions`).

- [x] 1.5a. **Migration `0028_trade_proposal_state.py`** — add `state` (NOT NULL DEFAULT `'pending_approval'`) + `rejection_reason` (TEXT NULL) + `rejected_at` (TIMESTAMPTZ NULL) to `trade_proposals`. CHECK constraint `state IN ('pending_approval','approved','rejected','expired')`. Backfill existing rows with `state='approved'` (conservative — keeps legacy proposals out of any first-toggle-off drain).
- [x] 1.5b. **`apps/api/src/iguanatrader/contexts/trading/models.py::TradeProposal`** — add the 3 columns + extend `__append_only_mutable_columns__` whitelist (same pattern `Trade` already uses for its close-flow columns) + CHECK constraint on `state` at the model layer.
- [x] 1.5c. **`apps/api/src/iguanatrader/contexts/trading/repository.py::TradeProposalRepository.set_state`** — new method; transitions a proposal to `approved`/`rejected`/`expired` + stamps `rejected_at` on terminal states.
- [x] 1.5d. **`apps/api/src/iguanatrader/contexts/trading/service.py`** — hook `set_state(..., 'approved')` into `execute_on_approval_handler` (after the proposal-load success branch); hook `set_state(..., 'expired' or 'rejected', reason)` into `proposal_rejected_handler` (collapsing `reason='approval_timeout'` to `expired`).

## Phase 2 — daemon drain + reconcile semantics

> **Architecture-adaptation note**: the spec assumed a `TradingDaemon` class with a `tick()` main loop. The actual codebase is APScheduler-driven (no tick loop, no `TradingDaemon` class — the daemon is `cli.trading._run_daemon` which registers cron jobs and bus subscribers). The tasks below adapt the spec semantics to the scheduler-driven shape: the toggle gate lives at the top of each propose cron handler, the heartbeat is a 10s cron job, drain + reconcile are bus subscribers, and boot reconcile runs once before `scheduler.start()`.

- [x] 5. **`apps/api/src/iguanatrader/contexts/orchestration/service.py::bootstrap_routines`** — gate every propose cron handler on `trading_enabled` for the daemon's `(tenant_id, mode)`. Reads at the top of each routine via `TradingModeRepository.load_trading_enabled`; short-circuits with structlog breadcrumb `orchestration.propose.skipped_disabled` when off.
- [x] 6. **`apps/api/src/iguanatrader/contexts/trading/daemon_lifecycle.py::DaemonLifecycleService._drain_pending_proposals`** — bulk `UPDATE trade_proposals SET state='rejected', rejection_reason='daemon_drained', rejected_at=now() WHERE mode=:mode AND state='pending_approval'`. Triggered by `DaemonDrainRequested` event filtered to this daemon's mode. Idempotent — second drain in same toggle finds no pending rows and updates 0.
- [x] 7. **`apps/api/src/iguanatrader/contexts/orchestration/service.py` — `daemon_heartbeat` JobSpec** — 10s cron (`second="*/10"`) calling `TradingModeRepository.write_heartbeat` with `ib_connected` derived from `broker.state == ConnectionState.CONNECTED`. Fires unconditionally so disabled daemons still surface as alive (no false "down" signal in the chip).
- [x] 8. **`DaemonLifecycleService.reconcile_with_ibkr`** — first cut: delegates to existing `TradingService.startup_reconcile()` for fills + writes an `EquitySnapshot(snapshot_kind='event')` row from `broker.get_account_equity()`. **Position-side reconcile deferred to Phase 2.5** (needs `BrokerPort.list_positions()` + a fake-adapter fixture + extending the `Trade.exit_reason` CHECK to include `'ibkr_reconcile'`).
- [x] 9. **`DaemonLifecycleService._reconcile_handler`** — bus subscriber for `DaemonReconcileRequested` (filtered by mode + tenant_id). Calls `reconcile_with_ibkr` with the event's correlation_id for trace continuity. Registered `idempotent=True` so retries collapse.
- [x] 10. **Boot reconcile wiring in `cli/trading.py::_run_daemon`** — after `lifecycle_service.register_subscriptions()` and before `scheduler.start()`: read the `trading_enabled` flag; if true, call `lifecycle_service.reconcile_with_ibkr()`; if false, log `trading.daemon.boot_reconcile.skipped_disabled` and skip. The existing `trading_service.startup_reconcile()` call stays as the unconditional broker-fills drain (covers disabled-boot crash-recovery; idempotent at `broker_fill_id`).

## Phase 2.5 — position-side reconcile (deferred)

Acceptance criterion 5 from `proposal.md` (`local trades close with provenance='ibkr_reconcile'`) needs the following follow-ups before the slice can archive:

- [ ] 2.5a. **Migration `0029_trade_exit_reason_extend.py`** — extend the `ck_trades_exit_reason_allowed` CHECK to allow `'ibkr_reconcile'` (existing set: `stop` / `target` / `manual` / `expiry`). Also update `Trade.__table_args__` model-side CHECK to match.
- [ ] 2.5b. **`BrokerPort.list_positions() -> Iterable[Position]`** — add to the port + implement on `IBKRAdapter` (delegate to `IbAsyncIBClient.positions()`) + the fake adapter (parameterised fixture for the reconcile test).
- [ ] 2.5c. **`DaemonLifecycleService._reconcile_positions`** — load all open `Trade` rows for `(tenant_id, mode)`; intersect with `broker.list_positions()` symbol set; for each local trade whose symbol is absent from the broker book, `UPDATE` `state='closed'`, `closed_at=now()`, `exit_reason='ibkr_reconcile'`.
- [ ] 2.5d. **Integration test** — pre-seed 2 local open trades; fake broker returns only 1 of them; assert the other transitions to `closed`/`exit_reason='ibkr_reconcile'`.

## Phase 3 — API endpoints

- [x] 11. **`apps/api/src/iguanatrader/api/routes/status.py`** — `GET /api/v1/status` per proposal §3. Session-auth (any logged-in user; admin-only deferred — MVP is single-seat, role gate adds no value yet). Stale-heartbeat (>30s) detection collapses `ib_connected` to false regardless of persisted value.
- [x] 12. **`apps/api/src/iguanatrader/api/routes/daemons.py`** — `POST /api/v1/daemons/{mode}/toggle` per proposal §3. Live toggle requires `password_reconfirm` + `reason` (>=20 chars); server re-verifies via `verify_password` (same Argon2id compare as login). 403 `password-mismatch` on failure.
- [x] 13. **Same file, `POST /api/v1/daemons/{mode}/reconcile`** — returns 202 Accepted with a generated `correlation_id` (operator can grep it against the daemon-side reconcile structlog events). The cross-process daemon-side wiring (poll for the request) lands in Phase 3.5.
- [x] 14. **Audit logging** — every toggle / reconcile request writes a structlog event `daemon.toggle` or `daemon.reconcile` tagged with `mode`, `user_id`, `reason`, `new_state` for the audit trail. The `audit_events` table sweep is a separate slice; structlog events are the durable record for now.
- [x] 15. **`apps/api/src/iguanatrader/api/dtos/status.py`** — Pydantic schemas `DaemonStatusOut`, `StatusResponse`, `DaemonToggleIn`, `DaemonToggleOut`, `DaemonReconcileOut`.
- [x] 16. **Register routes** — auto-discovery in [api/routes/__init__.py](../../../apps/api/src/iguanatrader/api/routes/__init__.py) picks up any module exporting `router: APIRouter`. New routes appear under `/api/v1/status` + `/api/v1/daemons/{mode}/(toggle|reconcile)`; OpenAPI docs reflect them automatically.

## Phase 3.5 — daemon-side cross-process bridge

The Phase 3 routes write to the DB (toggle) + log audit (reconcile), but the daemon and API run in **separate processes** (Phase 4 compose split makes this explicit). The in-process bus emit can't reach across — the daemon picks up state-changes via DB polling on the heartbeat cron tick.

- [x] 3.5a. **Migration `0029_tenant_trading_modes_reconcile_marker.py`** — adds `pending_reconcile_at TIMESTAMPTZ NULL` to `tenant_trading_modes`. (Renumbered to 0029 to follow Phase 1.5's 0028.)
- [x] 3.5b. **`daemons.py::reconcile_daemon`** — now calls `TradingModeRepository.mark_reconcile_pending` which UPDATEs `pending_reconcile_at = now()`. The response's `accepted_at` echoes the persisted timestamp so the operator can trace the request through to the daemon-side log entry.
- [x] 3.5c. **`DaemonLifecycleService.poll_for_state_changes`** — compares `last_toggled_at` + `pending_reconcile_at` against in-memory watermarks. First call initialises watermarks from current column values (no retroactive trigger on boot). Subsequent calls run drain when `enabled=false` AND `last_toggled_at` advanced; run reconcile when `pending_reconcile_at` advanced.
- [x] 3.5d. **Heartbeat cron poll hook in `orchestration/service.py`** — after `write_heartbeat` succeeds the cron also calls `daemon_lifecycle_service.poll_for_state_changes()`. Best-effort wrapper isolates poll failures from the heartbeat write loop.

## Phase 4 — compose split

- [x] 17. **`docker-compose.mvp.yml`** — split `trading_daemon` into `trading_daemon_paper` + `trading_daemon_live`. Each retains `--mode=paper|live` CLI arg (the daemon already reads it; no env-var replacement needed). Each with its own `IBKR_CLIENT_ID` (1 paper / 2 live) + own scheduler jobstore file (`iguanatrader_scheduler_{paper,live}.db`) so the cron history does not cross between modes.
- [x] 18. **`docker-compose.ibgateway.yml`** — split `ib-gateway` into `ib-gateway-paper` (port 4002, VNC `127.0.0.1:5900`) + `ib-gateway-live` (port 4001, VNC `127.0.0.1:5901`). Both use a YAML anchor (`x-ib-gateway-base`) so the digest pin + image tag stay DRY. Healthcheck per port via `nc -z`. Daemon-side `depends_on` redefined in the overlay (Compose merge replaces dict values; we re-state api + openbb_sidecar alongside the new gateway gate).
- [ ] 19. **SOPS env split** — add `IBKR_USERNAME_LIVE`, `IBKR_PASSWORD_LIVE`, `IBKR_ACCOUNT_ID_LIVE` keys to `.secrets/live.env.enc` (keep existing `IBKR_USERNAME` / `IBKR_PASSWORD` as paper-side fallback for backwards compat). **OPERATOR-OWNED**: SOPS on Windows quirks (age key path, no `set` subcommand) make this delicate — better executed by the operator with the canonical decrypt → edit → encrypt cycle. Document rename plan in [docs/runbooks/ibkr-gateway-bringup.md](../../../docs/runbooks/ibkr-gateway-bringup.md) when shipping.
- [x] 20. **Compose env mapping** — paper daemon reads `IBKR_USERNAME` / `IBKR_PASSWORD` (with `TWS_USERID` / `TWS_PASSWORD` fallback for backwards compat); live daemon reads `IBKR_USERNAME_LIVE` / `IBKR_PASSWORD_LIVE` (with `TWS_USERID_LIVE` / `TWS_PASSWORD_LIVE` fallback). Both via host-env fall-through (operator exports from SOPS pre-`docker compose up`).

## Phase 5 — frontend

- [x] 21. **`apps/web/src/lib/status/types.ts`** — TypeScript mirrors of the new DTOs (DaemonMode, DaemonStatusOut, StatusResponse, DaemonToggleIn/Out, DaemonReconcileOut).
- [x] 22. **`apps/web/src/lib/status/client.ts`** — `fetchStatus()` + `toggleDaemon(mode, payload)` + `reconcileDaemon(mode)` over `useFetch` (returns either DTO or RFC 7807 Problem).
- [x] 23. **`apps/web/src/lib/stores/daemon-status.svelte.ts`** — Svelte 5 store with `$state`; polls every 5s while document.visibilityState === 'visible', pauses on hidden, refreshes immediately on resume. `start()` + `stop()` idempotent for layout-lifecycle wiring.
- [x] 24. **`apps/web/src/lib/components/DaemonModeChip.svelte`** — header chip; reads from the singleton store. Paper=warning yellow, live=destructive red (color-fixed per §D8); brightness encodes active state (enabled AND ib_connected). Pulse-dot animation when last_fill_at within 60s. Hover tooltip with mode-aware copy. Click is a stub log breadcrumb pending the toggle modal (task 26).
- [x] 25. **`apps/web/src/routes/(app)/+layout.svelte`** — `$effect` mounts the daemon-status store on first paint + cleans up on unmount. Two `<DaemonModeChip>` instances live in `TopBar.__actions` left of the existing ConnectionIndicator.
- [x] 26. **`apps/web/src/lib/components/DaemonToggleModal.svelte`** — opens on chip click. Two variants: paper (simple body + optional reason) + live (⚠️ header + REQUIRED reason >=20 chars + REQUIRED password re-entry). On submit calls `toggleDaemon()`; on `password-mismatch` (403) the modal stays open with "contraseña incorrecta" + cleared password field; on `live-toggle-payload-invalid` (422) surfaces the server detail. Uses the native `<dialog>` element + `$effect` to drive showModal/close from the controlling `open` prop.
- [x] 27. **`apps/web/src/routes/(app)/settings/+page.svelte`** — added §Daemons section: status table per mode (enabled / ib_connected / last_heartbeat_at / last_fill_at / pending_proposals_count) + `Toggle` button (opens the same modal) + `Reconcile` button (calls `reconcileDaemon` + surfaces the correlation_id). Audit-log preview of last 10 toggle events deferred to the future audit-log slice (no existing query helper).
- [x] 28. **`apps/web/src/lib/components/Badge.svelte` + `apps/web/src/routes/(app)/proposals/+page.svelte`** — extended `BadgeVariant` with `'warning'` (yellow). `/proposals` list now renders the mode column as a Badge with `paper → warning` + `live → destructive` (matching the chip color contract).

## Phase 6 — tests

- [x] 29/30/33. **`apps/api/tests/integration/test_daemon_routes_smoke.py`** — consolidated smoke pass covering: migration-equivalent seeded rows + status endpoint shape + paper toggle happy path + live toggle missing-password/short-reason (422) + wrong-password (403) + correct-password+valid-reason (200) + reconcile stamps `pending_reconcile_at`. 7/7 green locally.
- [ ] 31. **`apps/api/tests/integration/test_daemon_drain.py`** — integration drain test (bus event → bulk reject + idempotency check + IBKR-fake no cancel calls). Deferred to next session; happy-path is exercised indirectly by `poll_for_state_changes` but a dedicated integration test is still needed.
- [ ] 32. **`apps/api/tests/integration/test_daemon_reconcile.py`** — fake-IBKR end-to-end reconcile test. Deferred — depends on Phase-2.5 position reconcile + a `BrokerPort.list_positions()` fake fixture.
- [ ] 34. **`apps/api/tests/unit/contexts/trading/test_trading_daemon_drain.py`** — pure-unit drain idempotency test. Deferred — overlaps significantly with the smoke test; revisit if the route-layer test misses a regression.
- [ ] 35. **`apps/web/tests/e2e/daemon-chip.spec.ts`** (Playwright) — chip renders, polls, opens toggle modal on click. Deferred to next session; depends on the modal (task 26) landing.

## Phase 7 — docs + housekeeping

- [x] 36. **`docs/runbooks/ibkr-gateway-bringup.md`** — appended §7 "Dual-daemon (paper + live) bring-up + toggle / reconcile via the UI": operator chip-toggle flow, on-demand reconcile button, drain semantics + the SQL it issues, pre-live-toggle checklist (5 items). The original §1+§2 single-gateway content still applies; the overlay file (`docker-compose.ibgateway.yml`) is what changes between single and dual.
- [ ] 37. **`docs/roadmap-ops.md`** — mark O4 `merged` post-PR-merge. **Deferred to the post-merge step** (the file references this slice by name; updating it on the same branch as the slice creates a chicken-and-egg loop with `/opsx:archive`).
- [ ] 38. **`docs/roadmap-ui.md`** — mark U-next-1 (global mode indicator) `merged`. Same reason as task 37; flip post-merge.
- [x] 39. **Memory update** — `project_dual_daemon_architecture.md` written + linked from `MEMORY.md`; covers compose shape + DB tables + cross-process poll (the part future sessions can't derive from the compose files alone).
- [x] 40. **Lint** — ruff + black clean on all touched Python files. svelte-check on the new TS/Svelte files reports no errors (the 5 pre-existing errors in unrelated files were not touched). mypy --strict not run as a separate pass — the codebase's mypy CI step runs strict and will surface any remaining issues at PR time.

## Phase 8 — PR + sign-off

- [ ] 41. Push branch `slice/dual-daemon-mode-toggle-and-reconcile`.
- [ ] 42. `gh pr create` with §4.5 self-review block + canonical AI-reviewer signoff stub.
- [ ] 43. STOP after `gh pr create`. Parent monitors CI.
- [ ] 44. Post-merge: `/opsx:archive 2026-05-18-dual-daemon-mode-toggle-and-reconcile` → promotes to `openspec/specs/` + drafts retro.
