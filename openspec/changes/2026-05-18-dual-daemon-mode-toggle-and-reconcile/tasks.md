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

- [ ] 5. **`apps/api/src/iguanatrader/cli/trading.py::TradingDaemon`** — add main-loop guard per proposal §4. Read `trading_enabled` at top of every tick; if false, run `_handle_drain_if_pending()` + `_heartbeat()` + return.
- [ ] 6. **`TradingDaemon._handle_drain_if_pending()`** — bulk-reject pending_approval proposals for this daemon's mode with `rejection_reason='daemon_drained'`. Idempotent (only acts if `drain_pending` flag set).
- [ ] 7. **`TradingDaemon._heartbeat()`** — write to `daemon_heartbeats` every tick with current IBKR connection state. Use 10s minimum interval (`last_write_at + 10s > now`) to avoid hammering the DB.
- [ ] 8. **`TradingDaemon._reconcile_with_ibkr()`** — extract from existing `iguanatrader trading reconcile` CLI into a reusable method on the daemon class. Both the CLI and the new HTTP endpoint will call it.
- [ ] 9. **Reconcile-on-resume wiring** — when bus event `daemon.reconcile.requested(mode)` arrives, set `self.pending_reconcile_request = True`. First subsequent tick runs reconcile before normal logic.
- [ ] 10. **Reconcile-on-boot wiring** — daemon `__aenter__()` or equivalent calls `_reconcile_with_ibkr()` before entering the main loop. Skip if `enabled=false` (just heartbeat and idle).

## Phase 3 — API endpoints

- [ ] 11. **`apps/api/src/iguanatrader/api/routes/status.py`** — new file. `GET /api/v1/status` per proposal §3. Session-auth required.
- [ ] 12. **`apps/api/src/iguanatrader/api/routes/daemons.py`** — new file. `POST /api/v1/daemons/{mode}/toggle` per proposal §3. Admin-role-gated. Live toggle requires `password_reconfirm` field; server verifies via the same hash-compare as login.
- [ ] 13. **Same file, `POST /api/v1/daemons/{mode}/reconcile`** — emits `daemon.reconcile.requested(mode)` bus event; returns 202 Accepted with a poll URL stub.
- [ ] 14. **Audit logging** — every toggle/reconcile request writes a structlog event `daemon.toggle` or `daemon.reconcile` tagged with `mode`, `user_id`, `reason`, `new_state` for the audit trail.
- [ ] 15. **`apps/api/src/iguanatrader/api/dtos/status.py`** — Pydantic schemas `DaemonStatusOut`, `StatusResponse`, `DaemonToggleIn`, `DaemonToggleOut`.
- [ ] 16. **Register routes** in `apps/api/src/iguanatrader/api/main.py` (or wherever routers are aggregated). Verify OpenAPI docs reflect new endpoints.

## Phase 4 — compose split

- [ ] 17. **`docker-compose.mvp.yml`** — split `trading_daemon` into `trading_daemon_paper` and `trading_daemon_live`. Each with its own `IGUANATRADER_DAEMON_MODE` env (replaces the `--mode=paper` CLI arg pattern; daemon reads the env at boot). Each with its own `IBKR_CLIENT_ID` (1 paper, 2 live). Both depend on `api` + `openbb_sidecar`.
- [ ] 18. **`docker-compose.ibgateway.yml`** — split `ib-gateway` into `ib-gateway-paper` (port 4002) and `ib-gateway-live` (port 4001). Each digest-pinned. VNC ports `127.0.0.1:5900` (paper) + `127.0.0.1:5901` (live). Healthchecks per port.
- [ ] 19. **SOPS env split** — add `IBKR_USERNAME_LIVE`, `IBKR_PASSWORD_LIVE`, `IBKR_ACCOUNT_ID_LIVE` keys to `.secrets/live.env.enc` (keep existing `IBKR_USERNAME` / `IBKR_PASSWORD` as paper-side fallback for backwards compat). Document the rename plan in [docs/runbooks/ibkr-gateway-bringup.md](../../../docs/runbooks/ibkr-gateway-bringup.md).
- [ ] 20. **Compose env mapping** — paper daemon reads `IBKR_USERNAME` / `IBKR_PASSWORD`; live daemon reads `IBKR_USERNAME_LIVE` / `IBKR_PASSWORD_LIVE`. Both via host-env fall-through (operator exports from SOPS pre-`docker compose up`).

## Phase 5 — frontend

- [ ] 21. **`apps/web/src/lib/status/types.ts`** — TypeScript mirrors of the new DTOs.
- [ ] 22. **`apps/web/src/lib/status/client.ts`** — `fetchStatus()` + `toggleDaemon(mode, payload)` + `reconcileDaemon(mode)` functions calling the new endpoints.
- [ ] 23. **`apps/web/src/lib/stores/daemon-status.svelte.ts`** (Svelte 5 store with `$state`) — polls `/api/v1/status` every 5s when document visible, pauses on hidden. Exposes `status: StatusResponse | null` and `error: string | null`.
- [ ] 24. **`apps/web/src/lib/components/DaemonModeChip.svelte`** — the layout-header chip. Props: `mode: 'paper' | 'live'`. Reads from `daemon-status` store. Visual states (dim/saturated, pulse-on-recent-fill, hover-tooltip) per proposal §5.
- [ ] 25. **`apps/web/src/routes/(app)/+layout.svelte`** — mount two `<DaemonModeChip>` instances in the top-right header. Initialize the daemon-status store on mount; destroy on unmount.
- [ ] 26. **`apps/web/src/lib/components/DaemonToggleModal.svelte`** — opens on chip click. Two variants: paper (simple) + live (with `⚠️` header, required reason ≥20 chars, password re-entry). On submit, calls `toggleDaemon()`. Handles 403 password_mismatch.
- [ ] 27. **`apps/web/src/routes/(app)/settings/+page.svelte`** — add §Daemons section per proposal §5. Status table + per-daemon `Reconcile` + `Toggle` buttons. Pulls from the same store.
- [ ] 28. **`apps/web/src/lib/proposals/variants.ts`** — extend mode badge: `paper` → `warning` (yellow), `live` → `destructive` (red). Update `/proposals` list column to use prominent badge instead of muted grey text. ~15 LOC.

## Phase 6 — tests

- [ ] 29. **`apps/api/tests/integration/test_tenant_trading_modes.py`** — migration applies + seeds. Default values per spec. Cascade-on-tenant-delete works.
- [ ] 30. **`apps/api/tests/integration/test_daemon_toggle_endpoint.py`** — happy paths (paper toggle, live toggle with correct password), failure paths (wrong password 403, non-admin 403, invalid mode 400, missing reason for live 422).
- [ ] 31. **`apps/api/tests/integration/test_daemon_drain.py`** — seed 3 pending_approval proposals; toggle mode off; assert all 3 transition to rejected with reason='daemon_drained'; IBKR-fake records no cancel calls.
- [ ] 32. **`apps/api/tests/integration/test_daemon_reconcile.py`** — seed local trades absent from fake IBKR; call reconcile endpoint; assert local closes with provenance='ibkr_reconcile'.
- [ ] 33. **`apps/api/tests/integration/test_status_endpoint.py`** — shape + auth + stale-heartbeat detection (ib_connected=false when last_heartbeat > 30s old).
- [ ] 34. **`apps/api/tests/unit/contexts/trading/test_trading_daemon_drain.py`** — unit tests for `_handle_drain_if_pending()` idempotency.
- [ ] 35. **`apps/web/tests/e2e/daemon-chip.spec.ts`** (Playwright) — chip renders, polls, opens toggle modal on click, blocks live submission without password.

## Phase 7 — docs + housekeeping

- [ ] 36. **`docs/runbooks/ibkr-gateway-bringup.md`** — update §1 + §2 to reflect two gateways. Add §7 "Daemon toggle + reconcile via UI" pointing operator at `/settings` + the chip.
- [ ] 37. **`docs/roadmap-ops.md`** — mark O4 `merged` post-PR-merge.
- [ ] 38. **`docs/roadmap-ui.md`** — mark U-next-1 (global mode indicator) `merged`.
- [ ] 39. **Memory update** — add a new project memory `project_dual_daemon_architecture.md` summarising the dual-daemon shape so future sessions don't re-derive it from compose files.
- [ ] 40. **Lint** — scoped ruff + black + mypy --strict on all touched Python files. eslint + svelte-check on touched TS/Svelte files.

## Phase 8 — PR + sign-off

- [ ] 41. Push branch `slice/dual-daemon-mode-toggle-and-reconcile`.
- [ ] 42. `gh pr create` with §4.5 self-review block + canonical AI-reviewer signoff stub.
- [ ] 43. STOP after `gh pr create`. Parent monitors CI.
- [ ] 44. Post-merge: `/opsx:archive 2026-05-18-dual-daemon-mode-toggle-and-reconcile` → promotes to `openspec/specs/` + drafts retro.
