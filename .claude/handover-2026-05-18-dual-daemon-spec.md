# Handover — last updated 2026-05-25

> Paste into fresh Claude Code session. Drop as first message.

## State

- Repo `c:\Projects\iguanatrader`, branch `main`, clean.
- Dual-daemon foundation **shipped** (PR #265). All Phase 1-7 tasks done. Spec archived → `openspec/changes/archive/2026-05-18-dual-daemon-mode-toggle-and-reconcile/`.
- 4 follow-up slices (O5/O6/O7 + O1/O3 ops) still `proposed`, not started.

## Shipped since spec landed

| PR | Slice |
|---|---|
| #261 | gnzsnz digest pin + MCP token in SOPS + roadmap-ops |
| #262 | dual-daemon OpenSpec change |
| #265 | dual-daemon impl (paper+live + toggle + reconcile + chips) |
| #266 | dual-daemon Phase 2.5 + Phase 6 follow-ups |
| #267 | A2 risk-review persistence |
| #268 | SOPS IBKR creds hardening (Task 19) |
| #269 | roadmap flips A0-A3 + Task 19 |
| #270 | U-next-2 trade timeline + variant fix |
| #271 | U-next-2 roadmap flip |

## Pending — operational (high impact, do first)

1. **VPS deploy** — all merged code sits on main, not yet on cx43. roadmap rows say "pending VPS deploy". Bring-up runbook: `docs/runbooks/ibkr-gateway-bringup.md` §0 + §1.
2. **Live IBKR creds** — `.secrets/live.env.enc` still placeholder. Populate before flipping live daemon `enabled=true` via UI chip.
3. **`IGUANATRADER_MCP_TENANT_SLUG`** — empty in both SOPS envs. MCP routes return 503 until populated. No Hermes consumer yet → not urgent.
4. **Image digest cert** — gnzsnz pin expires when IBKR rotates EV cert (~2026-08-04, auto). Re-pin manually quarterly (O3 cron not built).

## Pending — slices (proposed, not arrancadas)

| Slice | Where | Notes |
|---|---|---|
| **O5** per-mode strategy gating | `docs/roadmap-ops.md:111` | adds `Strategy.enabled_modes`. Enables paper→live promotion workflow. ~250 LOC + 1 migration. |
| **O6** strategy health observability | `docs/roadmap-ops.md:123` | last_run_at, last_error_text, signals_today, win_rate, sharpe. B1+B2+B3 bundled. ~400 LOC + 1 migration. **Should ship before live cutover** — today no UI signal if strategy silently broken. |
| **O7** trades-filters + shadow mode | `docs/roadmap-ops.md:137` | generic filter component + `Trade.state='shadow'` + shadow daemon variant. ~500 LOC + 1 migration. Prereq: O4 (done). |
| **O1/O8** sops-decrypt-at-boot | `docs/roadmap-ops.md` | container entrypoint shim. Removes manual env exports. ~150 LOC. |
| **O3** quarterly digest refresh workflow | `docs/roadmap-ops.md:85` | GH Actions cron on 1st of Jan/Apr/Jul/Oct. ~30 LOC. |
| **U-next-3** trades filters panel | folded into O7 | |

## Pending — residual from archived spec

- **Task 35 only**: Playwright e2e for daemon-chip. **Deferred** — no Playwright runner exists yet in `apps/web/`. Standalone slice when runner lands.

## Locked decisions (don't re-litigate)

1. Dual-daemon = two processes, not one multi-mode. Failure isolation.
2. DB flag (`tenant_trading_modes`) not docker-control. Security blast radius.
3. Drain: reject pending_approval, leave IBKR-side orders. **IBKR siempre manda**.
4. Reconcile-on-resume MANDATORY. Also on-demand button in `/settings`.
5. Password re-entry for live toggle. Not for paper.
6. Color = risk-fixed (paper=yellow, live=red). Brightness = active.
7. Live defaults `enabled=false` on migration 0020.
8. Shadow mode = scope of O7. Per-mode gating = scope of O5. Strategy health = scope of O6.

## Operator preferences (memory)

- ISO 8601 dates everywhere.
- No A/B/C menus for declared positions.
- Never `git add -A` → sweeps `.claude/worktrees/`. Stage explicit paths.
- Delete don't disable. KISS, DRY.
- `/ultrareview` user-triggered only.

## Anti-patterns recordadas

- SOPS Windows: `SOPS_AGE_KEY_FILE=C:/Users/Arturo/.config/sops/age/keys.txt`. Default path Windows wrong.
- SOPS 3.7.3 no `set` subcommand → decrypt-edit-encrypt cycle. `--age age10nqq3zd2t88nzym3wr95ju5rt0la9m3363sdnm8xfx44davzg4hqk0qh00` explicit.
- Docker Desktop down → Docker Hub API: `curl https://hub.docker.com/v2/repositories/<image>/tags/<tag>`.
- `gdcdyn.interactivebrokers.com` legítimo. DigiCert EV `O=IBG LLC, Greenwich, Connecticut`. `Xdcdyn` = regional family (g=EU, n=NA, c=Asia).

## Concrete next actions (pick one)

A) **Deploy actual a cx43** — bring-up runbook + populate live creds + flip live chip. Validate paper-only operation 1-2 semanas before live.

B) **Arrancar O6** strategy health — independent, no prereq, must-have antes de live. `/opsx:propose strategy-health-observability`.

C) **Arrancar O1** sops-decrypt-at-boot — quality-of-life pre-deploy. `/opsx:propose sops-decrypt-at-boot`.

D) **Arrancar O5** per-mode strategy gating — unlocks paper→live promotion. Prereq O4 ✅.

## Key files

- `openspec/changes/archive/2026-05-18-dual-daemon-mode-toggle-and-reconcile/{proposal,design,tasks}.md` — reference, archived.
- `docs/roadmap-ops.md` — O1-O8.
- `docs/roadmap-ui.md` — U-next-1 (merged), U-next-2 (merged), U-next-3 (folded into O7).
- `docs/runbooks/ibkr-gateway-bringup.md` — §0 security checklist + §1-7 bring-up.
- `.secrets/{paper,live}.env.enc` — credentials.
- `docker-compose.{mvp,ibgateway}.yml` — compose stack.

## Memory entries

Existing (`C:\Users\Arturo\.claude\projects\c--Projects-iguanatrader\memory\`):
- `project_vps_deployment_state.md` — cx43 + ssh alias + paths.
- `project_ci_pytest_collect_only.md` — CI --collect-only ≠ tests pass.
- `feedback_never_git_add_dash_A.md`.
- `feedback_date_format_preference.md`.
- `feedback_no_menus_for_clear_decisions.md`.
- `project_dual_daemon_architecture.md` (added post-merge per Task 39).

## Verification before trusting this doc

```bash
git log --oneline -10
gh pr list --state open
ls openspec/changes/  # active slices, if any
```

If recent commits ≠ what's listed in "Shipped" above, doc is stale.
