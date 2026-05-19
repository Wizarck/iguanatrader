# Handover — 2026-05-18 — dual-daemon spec + IBKR hardening

> **For pasting into a fresh Claude Code conversation.** Drop the contents below as your first message so the new session has full context.

---

## Project state

- Repo: `c:\Projects\iguanatrader` (Wizarck/iguanatrader on GitHub)
- Operator: Arturo Ramírez
- Current branch: `slice/dual-daemon-mode-toggle-and-reconcile` (don't switch off without committing)
- Main is at commit `b91f276` (PR #260 merged 2026-05-17)

## Open PRs (in merge order)

1. **PR #261** — https://github.com/Wizarck/iguanatrader/pull/261
   `ops/ibgateway-digest-mcp-token-sops` → main
   - Pins `gnzsnz/ib-gateway` by `sha256:a9a771b0...` (audit verdict: SAFE, EV cert from DigiCert with subject `O=IBG LLC`)
   - Adds `IGUANATRADER_MCP_TOKEN` (256-bit hex) to `.secrets/{paper,live}.env.enc`
   - Wires `IGUANATRADER_MCP_TOKEN` + `IGUANATRADER_MCP_TENANT_SLUG` in `docker-compose.mvp.yml` api service
   - New `docs/roadmap-ops.md` (O1 sops-decrypt-at-boot, O2 IB Gateway prod cutover, O3 quarterly digest refresh)
   - §0 Security pre-bring-up checklist in `docs/runbooks/ibkr-gateway-bringup.md` (9 hardening items, applies to paper AND live)
   - Status: ready for review; CI probably running

2. **PR #262** — https://github.com/Wizarck/iguanatrader/pull/262
   `slice/dual-daemon-mode-toggle-and-reconcile` → `ops/ibgateway-digest-mcp-token-sops`
   - Specs-only PR (no code). Opens OpenSpec change `2026-05-18-dual-daemon-mode-toggle-and-reconcile/`
   - Contains `proposal.md` (200 lines), `design.md` (10 architectural decisions, 201 lines), `tasks.md` (44 numbered tasks, 8 phases)
   - Adds O4-O7 to roadmap-ops.md, U-next-1 to U-next-3 to roadmap-ui.md
   - Base will need retarget to main after #261 merges
   - Status: ready for review; awaits human approval (Gate E in OpenSpec workflow)

## What was decided this session (don't re-litigate)

1. **Dual-daemon split**: `trading_daemon_paper` + `trading_daemon_live` run in parallel, each with its own `ib-gateway` container.
2. **Research/ingest is shared** (mode-agnostic); strategies/proposals/risk are mode-scoped.
3. **`tenant_trading_modes(tenant_id, mode, enabled, last_toggled_*)`** is the toggle mechanism. NOT docker container start/stop (security blast radius).
4. **Drain semantics**: toggle-off rejects `pending_approval` proposals with `rejection_reason='daemon_drained'`; IBKR-side orders untouched (IBKR is authoritative — operator phrase).
5. **Reconcile-on-resume is MANDATORY** when re-enabling a daemon; also exposed as on-demand button in `/settings`.
6. **Password re-entry required for `mode=live` toggle**; not for paper.
7. **Color = risk-fixed, brightness = active**: paper chip always yellow, live chip always red. Red doesn't mean "down" — it means "real money is at risk."
8. **Default-off live** on migration 0020 (paper.enabled=true, live.enabled=false seeded).
9. **Live IBKR account confirmed approved** (operator answered yes 2026-05-18). Paper account is `DUR071858`.
10. **Shadow mode IN scope of follow-up O7** (operator approved after roundtable clarified it ≠ paper).
11. **Per-mode strategy gating IN scope of follow-up O5** (operator approved — enables paper→live promotion workflow).
12. **Strategy health observability IN scope of follow-up O6** (operator approved — all 3 layers B1+B2+B3 in one slice).

## Follow-up slices captured in roadmaps (DO NOT start without operator sign-off)

- **O5** per-mode strategy gating (`Strategy.enabled_modes`)
- **O6** strategy health observability (last_run_at, last_error, win_rate, sharpe, etc. — addresses "estrategia silenciosa falla y no lo ves" gap)
- **O7** trades-filters + shadow mode (generic filter component for `/trades` `/proposals` `/orders` + `Trade.state='shadow'` extension)
- **U-next-2** trade Order timeline (fixes the variants.ts 3-color bug + Order substate visualization on `/trades/[id]`)

## Operator preferences in force (from memory)

- ISO 8601 dates ONLY everywhere (code, docs, logs)
- No menus for clear decisions; don't convert declared positions to A/B/C
- Never `git add -A` (sweeps `.claude/worktrees/` — 15k+ files); always stage explicit paths
- Don't disable things — delete them (KISS, DRY, no residue tecnico)
- /ultrareview before final merge if requested (multi-agent cloud review, user-triggered)

## Anti-patterns from THIS session — avoid repeating

- SOPS on Windows: `SOPS_AGE_KEY_FILE=C:/Users/Arturo/.config/sops/age/keys.txt` must be set. Key not at default `AppData/Roaming/sops/age/keys.txt`.
- SOPS 3.7.3 has no `set` subcommand; use decrypt → edit → encrypt cycle with explicit `--age age10nqq3zd2t88nzym3wr95ju5rt0la9m3363sdnm8xfx44davzg4hqk0qh00`.
- Docker Desktop not running locally — use Docker Hub registry API for digest lookups: `curl https://hub.docker.com/v2/repositories/<image>/tags/<tag>`.
- `gdcdyn.interactivebrokers.com` is legitimate IBKR — verified via DigiCert EV cert (subject `O=IBG LLC, Greenwich, Connecticut`). The `Xdcdyn` naming is IBKR's regional gateway-discovery family (g=Europe, n=North America, c=Asia).

## Next concrete action when resuming

1. Wait for PR #261 to merge (or merge it).
2. Retarget PR #262 base from `ops/ibgateway-digest-mcp-token-sops` to `main`.
3. After PR #262 approval (Gate E): run `/opsx:apply 2026-05-18-dual-daemon-mode-toggle-and-reconcile` to start implementation on a new `feat/dual-daemon-...` branch.
4. Implementation tracked in `openspec/changes/2026-05-18-dual-daemon-mode-toggle-and-reconcile/tasks.md` (44 tasks, 8 phases, ~5-6 days estimated).

## Pending but not blocking

- `IGUANATRADER_MCP_TENANT_SLUG` is empty in both SOPS .env files — operator must populate before MCP routes leave 503.
- Live IBKR account credentials in `.secrets/live.env.enc` still placeholder — populate before flipping live daemon enabled=true.
- O3 quarterly image-digest refresh workflow not yet automated.
- IBKR EV cert expires 2026-08-04 — IBKR will auto-rotate; no operator action needed.

## Key files to read first (in this order)

1. `openspec/changes/2026-05-18-dual-daemon-mode-toggle-and-reconcile/proposal.md` — what+why
2. `openspec/changes/2026-05-18-dual-daemon-mode-toggle-and-reconcile/design.md` — 10 architectural decisions
3. `openspec/changes/2026-05-18-dual-daemon-mode-toggle-and-reconcile/tasks.md` — execution plan
4. `docs/roadmap-ops.md` (only exists in PR #261 / PR #262 branches, not main yet)
5. `docs/runbooks/ibkr-gateway-bringup.md` — §0 has the security pre-bring-up checklist

## Memory entries that might be relevant

Already in memory (`C:\Users\Arturo\.claude\projects\c--Projects-iguanatrader\memory\`):
- `project_vps_deployment_state.md` — cx43 VPS, ssh alias, compose paths
- `project_ci_pytest_collect_only.md` — CI runs --collect-only, green CI ≠ tests pass
- `feedback_never_git_add_dash_A.md` — always stage explicit paths
- `feedback_date_format_preference.md` — ISO 8601 only
- `feedback_no_menus_for_clear_decisions.md` — don't convert positions to A/B/C

Should be added after slice merges (tasks.md #39):
- `project_dual_daemon_architecture.md` — summary of the dual-daemon shape so future sessions don't re-derive from compose files
