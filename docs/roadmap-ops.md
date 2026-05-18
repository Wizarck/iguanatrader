---
type: roadmap
project: iguanatrader
schema_version: 1
created: 2026-05-18
updated: 2026-05-18
purpose: Forward-looking slice plan for operational / infrastructure work — secrets handling, broker connectivity, image hygiene. Items here don't fit the LLM-features or UI tracks but are prerequisite for productionising the VPS deployment.
---

# Roadmap — Ops / infrastructure track

Single source of truth for ops slices that touch deployment, secrets, broker connectivity, and image-supply-chain hygiene. Lean — each row points at a future slice; when work starts, open an OpenSpec change and link it back here.

**Track owner**: Arturo Ramírez.
**Scope**: anything under `docker-compose.*.yml`, `.secrets/`, `docs/runbooks/`, plus deployment-side workflows in `.github/workflows/`.

## Status legend

- `proposed` — described here, no implementation work yet
- `in-progress` — branch open, OpenSpec change exists
- `merged` — code on main
- `deployed` — running in production on the VPS
- `parked` — descoped or deferred indefinitely

---

## O1 — sops-decrypt-at-boot

**Status**: proposed
**Prereq**: nothing (the SOPS files already exist in `.secrets/{paper,live}.env.enc`).
**Estimated**: ~150 LOC + a small container entrypoint shim.

### Why

Today the operator manually exports env vars in their shell before `docker compose up` (see [docs/runbooks/ibkr-gateway-bringup.md](runbooks/ibkr-gateway-bringup.md) step 1). That means:
- Secrets sit in shell history (`HISTFILE`) and the operator's environment.
- Restarting the host loses them — operator must re-export from the password manager.
- No clear audit trail for what's loaded vs what's still defaulted.

A boot-time SOPS decrypt would mount the age key from `~/.config/sops/age/keys.txt`, decrypt `.secrets/{paper,live}.env.enc` once at container start, and populate `os.environ` in-process before the FastAPI app boots. Plaintext never lives on disk.

### Components

- Container entrypoint shim (`apps/api/scripts/sops-bootstrap.sh`) that runs `sops -d` and `eval $(sops -d ... --output-type dotenv ...)` before the actual `iguanatrader api serve` command.
- Compose-level: mount `~/.config/sops/age/keys.txt` read-only into the `api` and `trading_daemon` containers.
- Profile gate: only enabled when `IGUANATRADER_ENV` in `{paper, live}`; dev profile keeps the current plaintext env path.
- Decision (capture in ADR): which env vars are SOPS-only vs which can stay in compose. Proposal: anything credential-shaped (`*_PASSWORD`, `*_TOKEN`, `*_SECRET`, `*_API_KEY`) goes SOPS-only; everything else stays in compose with `:-` defaults.

### Open questions

- Should age key be mounted from host filesystem, or shipped via Docker Secrets (compose `secrets:` block)? Filesystem mount is simpler; Docker Secrets is more idiomatic for swarm/k8s but iguanatrader is single-host.
- What about rotation? Re-encrypting with a new age recipient is a `sops updatekeys .secrets/*.enc` one-liner — out of scope for O1 but documented in the runbook.

---

## O2 — IB Gateway production cutover

**Status**: in-progress (overlay shipped, paper account pending IBKR approval, credentials still manual)
**Prereq**: O1 (so `TWS_USERID`/`TWS_PASSWORD` flow from SOPS instead of manual export)
**Estimated**: ~50 LOC + paper-account validation + 1 cutover dry-run.

### Shipped

- [docker-compose.ibgateway.yml](../docker-compose.ibgateway.yml) overlay using `gnzsnz/ib-gateway:stable@sha256:...` (digest-pinned 2026-05-18 after security audit).
- [docs/runbooks/ibkr-gateway-bringup.md](runbooks/ibkr-gateway-bringup.md) covers paper bring-up, smoke test, paper→live cutover, 2FA via VNC tunnel.
- Paper credentials present in `paper.env.enc` (`IBKR_USERNAME`, `IBKR_PASSWORD`).

### Pending

- Validate paper account `okqtbz074` / `DUR071858` is approved IBKR-side (was pending as of 2026-05-15).
- First end-to-end bring-up on the VPS — the runbook has not been executed yet, only authored.
- Reconcile env-var naming drift: the SOPS dotenv uses `IBKR_USERNAME` / `IBKR_PASSWORD`; the gnzsnz image expects `TWS_USERID` / `TWS_PASSWORD`. The overlay aliases them (`IBKR_USERNAME=${TWS_USERID}`) but a clean rename in SOPS + compose would remove the cognitive cost. Either rename SOPS keys to TWS_* (clean) or keep IBKR_* and alias in the gnzsnz env block (current).
- Live account credentials still placeholder in `live.env.enc` — populate when the operator decides to go live.

### Out of scope

- Litestream replication of the trading DB during live mode — covered separately in `docker-compose.yml`'s `litestream` service.

---

## O3 — Quarterly image-digest refresh policy

**Status**: proposed
**Prereq**: none.
**Estimated**: ~30 LOC (a single GitHub Actions workflow + a runbook stub).

### Why

`docker-compose.ibgateway.yml` now pins `gnzsnz/ib-gateway` by digest (audit mitigation, 2026-05-18). The same hardening should apply to every pulled image in the production stack — `iguanatrader/api:mvp` and `iguanatrader/web:mvp` are locally built so they're fine, but `gnzsnz/ib-gateway`, `iguanatrader/openbb-sidecar:mvp` (when published), and any base image used in our Dockerfiles need a refresh discipline.

### Components

- Calendar-quarter workflow (`.github/workflows/refresh-image-digests.yml`) that runs on the 1st of Jan/Apr/Jul/Oct: queries Docker Hub for the latest `:stable` digest of each pinned image, opens a PR with the diff against `docker-compose.ibgateway.yml` for human review (release notes attached).
- Runbook stub at `docs/runbooks/image-digest-refresh.md` documenting how to do it manually if the workflow is unavailable.
- Decision: which images are in-scope. Proposal: any third-party image pulled from Docker Hub at `:stable` or `:latest`. Self-built images (`iguanatrader/*:mvp`) are excluded — their provenance is the local build pipeline.

---

## O4 — dual-daemon split + mode-toggle + on-demand reconcile

**Status**: proposed (OpenSpec change drafted 2026-05-18: [openspec/changes/2026-05-18-dual-daemon-mode-toggle-and-reconcile/](../openspec/changes/2026-05-18-dual-daemon-mode-toggle-and-reconcile/))
**Prereq**: PR #261 merged (compose baseline + digest pin).
**Estimated**: ~700 LOC + 2 migrations + ~25 new tests. 5–6 days.

Split the single `trading_daemon` into parallel paper + live daemons each with its own IB Gateway, add a `tenant_trading_modes` flag, a `/api/v1/status` endpoint, a `/api/v1/daemons/{mode}/toggle` endpoint (password re-entry for live), an on-demand reconcile endpoint, persistent mode chips in the web header (color = risk-fixed, brightness = active), and a §Daemons section in `/settings` with a "Reconcile ahora" button.

Drain semantics: toggle-off rejects pending_approval proposals; IBKR-side orders remain untouched (IBKR is authoritative); reconcile-on-resume is mandatory. Full architectural rationale in the slice's `design.md`.

---

## O5 — per-mode strategy gating

**Status**: proposed
**Prereq**: O4
**Estimated**: ~250 LOC + 1 migration.

Add `Strategy.enabled_modes: list[str]` (subset of `{'paper','live'}`). Each daemon's strategy ticker filters to strategies whose `enabled_modes` includes its own mode. Enables the "validate in paper before promoting to live" workflow that Diana (compliance) flagged in the roundtable: a strategy newly authored can run in paper for two weeks, accumulate metrics, then be promoted to live by editing the row to add `'live'` to the list.

UI: `/strategies` list grows two columns (`Paper` checkbox + `Live` checkbox); `/strategies/[symbol]` form gains the same.

---

## O6 — strategy health observability

**Status**: proposed
**Prereq**: none (independent of O4-O5; ships in parallel).
**Estimated**: ~400 LOC + 1 migration + ~12 new tests.

Add the missing strategy-level observability fields the roundtable flagged: `last_run_at`, `last_error_text`, `last_error_at`, `signals_today`, `proposals_emitted_today`, plus per-strategy performance aggregates (`win_rate`, `realised_pnl_30d`, `max_drawdown_30d`, `sharpe_30d` — computed by a nightly cron from the `trades` table, mode-scoped).

UI surface: `/strategies` list grows status columns (last run, last error indicator, signals today); `/strategies/[symbol]` gains a §Health panel + §Performance metrics panel (per-mode breakdown).

Today there is no way to tell from the UI whether a strategy is silently broken — error-tracking is the must-have piece (B1 in the roundtable); activity + performance (B2/B3) ship together for one cohesive slice.

---

## O7 — trades-filters + shadow mode

**Status**: proposed
**Prereq**: O4 (shadow daemon writes against live book; needs the dual-daemon scaffolding).
**Estimated**: ~500 LOC + 1 migration + filter component.

Two intertwined concerns shipped together because the UI work overlaps:

1. **Generic filter component** for `/trades` (and reusable for `/proposals`, `/orders`): filter rows by symbol, strategy_kind, state, mode, date range. Today there is no filter UI on `/trades` — the whole table is rendered raw.
2. **Shadow mode**: extend `Trade.state` enum to include `shadow`. Add an optional shadow-daemon flag (`IGUANATRADER_DAEMON_SHADOW_FROM_LIVE=true`) — when enabled, the live daemon runs strategies against the live book but instead of submitting orders to IBKR, writes a Trade row with `state='shadow'` for audit / "what would have happened" inspection. Default filter on `/trades` hides shadow rows; user can toggle them in via the filter UI.

Iván (quant) in the roundtable: "shadow validates strategy decisions against live conditions without simulated-fill optimism."

---

## O8 — sops-decrypt-at-boot (renumbered from O1)

> **Note**: O1 in the original ordering. Renumbered here only for narrative flow; the slice itself is unchanged. See [O1 section above](#o1--sops-decrypt-at-boot).

---

## Out of scope for this track (future, not promised)

- Multi-host orchestration (k8s / swarm): single-host compose is canonical until the operator decides otherwise.
- Image signing (cosign / Notary v2) on our own `iguanatrader/*:mvp` images: low value when the only consumer is the same VPS.
- Centralised secrets manager (HashiCorp Vault, AWS Secrets Manager): SOPS + age covers the multi-operator scenario; no plan to migrate until a concrete need emerges.
