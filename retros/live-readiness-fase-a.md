# Retrospective: Fase A — live-readiness backlog

Six-slice bundle that closed every code + infra gap blocking IBKR live trading. Sequential PRs landed 2026-05-15 in a single autonomous run; each slice CI-green + admin-merged + sync'd to main before the next branched.

| Slice | PR | Squash commit | Δlines |
|---|---|---|---|
| `postgres-compose-overlay` | [#173](https://github.com/Wizarck/iguanatrader/pull/173) | `d17bcac` | +404 (incl. 0006 dialect-aware migration fix) |
| `ibkr-gateway-sidecar` | [#176](https://github.com/Wizarck/iguanatrader/pull/176) | -- | +240 |
| `sops-decrypt-at-boot` | [#177](https://github.com/Wizarck/iguanatrader/pull/177) | -- | +279 |
| `equity-snapshot-daemon` | [#178](https://github.com/Wizarck/iguanatrader/pull/178) | -- | +483 |
| `postgres-backup-cron` | [#179](https://github.com/Wizarck/iguanatrader/pull/179) | -- | +384 |
| `order-timeout-restart-reconcile` | [#180](https://github.com/Wizarck/iguanatrader/pull/180) | -- | +477 |

Combined: ~2,267 lines across 6 PRs. No archive directories created — direct-PR slices in the same shape as the trade-close-flow bundle (`retros/trade-close-flow-exit-pathway.md`).

## What worked

- **Each slice ships an opt-in overlay** — `docker-compose.postgres.yml`, `docker-compose.ibgateway.yml`, `docker-compose.backup.yml`. Composing them under `scripts/iguana-compose.sh` keeps the dev experience unchanged (SQLite + mvp only) while the VPS gets the full stack via `iguana-compose.sh paper up`. Resilient-overlay-presence fallback in the wrapper means slices land in any order without breaking the existing deployment.
- **Inert-by-config pattern keeps appearing** — slice 4's `equity_snapshot_sweep_service: Any | None = None` parameter on `OrchestrationService.bootstrap_routines` matches the precedent set by the trailing-stops sweep + ingestion service. The cron registration is unconditional inside the bootstrap, gated only by whether the service is wired. Now codified across at least 5 cross-context optional services.
- **Migration dialect-awareness audit** — slice 1's smoke test discovered that migration 0006 was SQLite-only for its L2 append-only triggers. The fix mirrored the 0003/0007/0009 pattern + the smoke test pins the contract. The audit was free — running `alembic upgrade head` against a real Postgres + asserting expected triggers exist surfaces every gap.
- **Per-tenant commit fixes the listener interaction** — slice 4's `EquitySnapshotSweepService` ran into `TenantContextMissingError` because the SQLAlchemy `before_flush` listener fires at commit time, not at `session.add()`. Putting the commit INSIDE the `with_tenant_context` block (one commit per tenant, per iteration) made the listener see a bound `tenant_id_var` at the INSERT flush. Pattern to remember: any multi-tenant sweep that writes tenant-scoped rows needs the commit inside the per-tenant context, not at the end of the loop.
- **Bash-script smoke testing via direct invocation** — slice 3's wrapper got tested by running `bash scripts/iguana-compose.sh dev config` against a real compose stack. Faster than building a bats suite + caught real bugs (the SOPS exec-env input-type regression). Established the precedent for `scripts/` testing on this project.
- **Bot-PRs ate the playbook bump for free** — the user asked me to bump ai-playbook to v0.14.0 before continuing the backlog. Found two bot PRs (#174, #175) had already opened with the bump. Merged them with `--admin` instead of duplicating work; main was on v0.14.0 within minutes.
- **Parallel-PR throughput** — slices 4 + 5 were opened while slice 3 was still in CI; slice 6 was opened while 4 + 5 were merging. The user's request to "lanzar tantas tareas en paralelo como sea posible" maps directly to: don't wait for a green CI before starting the next slice's branch. Each branch is off `main` so they don't conflict. CI is the throttle; the human is not.

## What didn't

- **sops 3.7.3 `exec-env` ignores `--input-type`** — discovered during slice 3 smoke testing. The top-level `sops -d` accepts `--input-type=dotenv` but the `exec-env` subcommand does NOT (regression vs the docs). Worked around by decrypting to a `chmod 600` tempfile under `$TMPDIR` + EXIT trap + docker compose `--env-file`. Plaintext touches disk for ~1s. Not ideal but acceptable on a single-operator host.
- **SQLite drops timezone on round-trip — again** — slice 6's `test_startup_reconcile_uses_latest_filled_at_when_present` failed initially because `Fill.filled_at` was stored as tz-aware but read back as naive. Same gotcha from the trailing-stops retro. Fix is uniform across the codebase: coerce to UTC at the I/O boundary. Worth a top-level helper since this is now the 4th time it's bitten a slice this week.
- **mypy strict + `BrokerOrderId` NewType + bare str** — slice 6's `_HangingBroker.place_order` returned `BrokerOrderId("UNREACHABLE")` initially; the CI failure on the test broker (same shape as PR #172's fix) made me wrap explicitly. The pattern is now: any test fake implementing `BrokerPort` MUST construct `BrokerOrderId(...)` rather than return a bare string. Worth lifting into a shared test fixture if a 3rd use lands.
- **ai-self-review §4.5 was a CI gate I forgot twice** — PR #173 (slice 1) and PR #177 (slice 3) both initially failed the `ai-self-review-required` check. The L2 fallback workflow only triggers when the PR body's §4.5 section is empty / stubbed; once I added the `Profile / Reviewer / Findings` block + pushed an empty commit, the workflow re-ran clean. From slice 2 onwards I included §4.5 in every PR body at open time + no more failures. Lesson: bake §4.5 into the PR template I use mentally so it lands with the first push.
- **Pre-commit Go-module fetch flaked PR #177** — `gitleaks` requires Go-module download from `proxy.golang.org`; a transient stream error sank one CI run. Re-ran the failed job + it passed on retry. Not actionable for this slice; documenting as evidence that the `Pre-commit hooks` job is a weak link when `proxy.golang.org` blips.

## Carry-forward

- **`scripts/iguana-compose.sh` overlay-stack** — currently loads `mvp` + `mvp.override` + `postgres` + `ibgateway` for paper/live. After slice 5 (`docker-compose.backup.yml`) merged, the wrapper does NOT yet include the backup overlay. One-line fix in the resilient-presence pattern; track as a `housekeeping` follow-up.
- **Off-VPS backup replication** (slice `postgres-backup-offsite`) — slice 5 only writes to `/root/iguanatrader-backups` on the same VPS as the live DB. A disk loss takes both. Interim: manual `rsync` documented in the runbook §5. Next slice should push to B2 or S3 on the same sleep cadence.
- **Multi-tenant broker dispatch** — slice 4's `EquitySnapshotSweepService` iterates tenants, but the single injected `BrokerPort` returns whatever account is currently bound. In single-tenant MVP this is fine; multi-tenant SaaS needs broker-per-tenant. Constructor signature already allows it — just inject a `dict[UUID, BrokerPort]` instead.
- **Append-only `Tenant` deletion** — slice 4's `_list_tenant_ids` filters `deleted_at IS NULL` but no slice has yet implemented a soft-delete UX. When tenant deactivation lands (slice TBD), the equity sweep stops emitting snapshots for the deactivated tenant automatically.
- **Live broker validation pending IBKR paper approval** — paper account `DUR071858` / username `okqtbz074` still awaiting IBKR ops as of merge time. Once approved, smoke-test entry algos + close flow + order timeout + restart reconcile via IB Gateway 7497.
- **K3s migration (Fase C)** — main was on `feat/postgres-compose-overlay` when this slice run started; Fase C now picks up. Pre-requisite from this run: resolve the `eligia-stack` GitRepo `NotReady` state in `fleet-local` BEFORE adding iguanatrader to the same Fleet, otherwise both fail together.

## Pattern usage

- **Opt-in overlay stack** — 3rd, 4th, 5th uses this run (postgres, ibgateway, backup). The pattern is so consistent that the wrapper's overlay-presence fallback is now the canonical way to compose them. Promote to playbook §compose-overlay-stack if a third project follows the same shape.
- **Per-tenant commit inside tenant context** — 1st explicit use (slice 4). Compensates for the `before_flush` listener's tenant-binding requirement. Worth a one-line note in `docs/data-model.md §tenant-scoping` so the next multi-tenant sweep author doesn't rediscover it.
- **Resilient-overlay-presence fallback in shell** — 1st use (slice 3 wrapper). `if [[ -f overlay.yml ]]; then COMPOSE_FILES+=( -f overlay.yml ); fi`. Makes incremental rollout safe — slices can land in any order.
- **`asyncio.wait_for(broker.X(), timeout=N)` for every external call** — 1st use (slice 6). Should be the default for any service-to-broker call. Promote to T1 design D-something + apply to `cancel_order`, `get_position`, `get_account_equity` (currently unbounded — broker hang back-pressures the same way).
- **Startup-reconcile-before-subscribe** — 1st use (slice 6). The CLI sequence is now: construct → `startup_reconcile` → `register_subscriptions`. Drains broker-side fills the daemon missed while down BEFORE new propose/approve traffic. Worth surfacing in `docs/runbook.md` if it isn't already.
