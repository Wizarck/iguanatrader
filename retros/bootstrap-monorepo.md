---
slice: bootstrap-monorepo
slice_number: 1
of_total: 20
wave: 0
merged: 2026-05-01
pr: https://github.com/Wizarck/iguanatrader/pull/22
gate_f_approved_by: arturo6ramirez@gmail.com
gate_f_approved_on: 2026-05-01
---

# Retro — slice 1 / `bootstrap-monorepo`

## What shipped

Monorepo skeleton + tooling baseline for iguanatrader. 50 tasks across 11 groups: pyproject Poetry workspace, pnpm workspace, root Makefile + per-slice `Makefile.includes` pattern, 4 docker-compose profiles (dev/paper/live/test) with litestream sidecar, `.github/workflows/*.yml` (ci, build-images, openapi-types, license-boundary-check), `.pre-commit-config.yaml` (gitleaks-first), `.secrets/*.env.enc` (SOPS+age, master key derived from `halamadrid` passphrase + `iguanatrader-master-key-v1` salt), LICENSE (Apache-2.0 + Commons Clause v1.0, byte-checksummed), 4 ADR drafts (014/015/016/017), `docs/getting-started.md`, `docs/gotchas.md` (10 entries).

## What worked well

- **OpenSpec spec-driven workflow + the slice plan.** The 50-task tasks.md kept the work atomic and reviewable. The `Depends on` column made wave ordering explicit; slice 2 onward will inherit the patterns slice 1 established.
- **Anti-collision contract.** Pre-declaring shared files (Makefile.includes, dynamic-discovery patterns) prevents the foreseeable collisions when Wave 2+ goes parallel.
- **Dogfooding the playbook.** This slice exposed 4 separate playbook bugs (rc1→rc6 progression). Without dogfooding through a real consumer, those would have shipped to multiple projects and surfaced later as systemic pain.

## What didn't work / surfaced friction

- **CI cascade**: the initial PR #22 CI run failed all 5 Python jobs because of one root cause (`poetry install --only main,dev` with `package-mode = false`). Took 5 commits to chain through poetry → submodule auth → playbook hook deps → editable install assumption → mcp-validate personal-layer requirement. Documented as gotchas #7-10.
- **Bump-bot pile-up**: shipping 6 rc tags during slice 1 (rc1→rc6) triggered the playbook's `propagate-playbook-bump.yml` 6 times. Each time it opened 2 PRs (playbook + skills) without superseding the previous ones, leaving 10 redundant PRs at end of slice. All closed at slice close-out; root-cause fix is upstream in `propagate-*-bump.yml` (Phase 2 follow-up).
- **GH Project v2 user/org-vs-repo scope confusion**: the project was created at user scope but didn't appear in the repo's Projects tab. Required explicit `linkProjectV2ToRepository` mutation (added to `bootstrap_gh_project.py` v0.8.0-rc3).

## Patterns to retain for future slices

- Each slice's PR description carries the `tasks.md` checklist verbatim, ticking off as commits land. Reviewer sees progress live.
- Per-slice `Makefile.includes` referenced via `-include apps/*/Makefile.includes` (lazy) lets each slice own its build steps without touching the root Makefile.
- ADRs drafted as skeletons during foundation slices, fully populated by the slices that touch the actual decision (e.g. ADR-015 OpenBB AGPL boundary fully populated by slice R4).
- Gotchas captured at slice close-out (this file's discovery surfaced 10 entries; future slices likely surface 0-2 each — fine, append-only log).

## Follow-ups created

| Item | Where | Owner |
|---|---|---|
| Bump-bot supersede logic | ai-playbook `propagate-{playbook,skills}-bump.yml` | Phase 2 |
| Self-contained playbook scripts (no editable-install assumption) | ai-playbook `scripts/*.py` add `sys.path.insert` | Phase 2 |
| `requirements-hooks.txt` for system-language pre-commit hook deps | ai-playbook root | Phase 2 |
| Decide whether `.mcp.json` should be committed at all | playbook spec discussion | Open question |
| Auto-transition Blocked→Todo workflow | iguanatrader `.github/workflows/project-status.yml` from playbook template | Phase 2 |
| Optional dep-check workflow | iguanatrader `.github/workflows/dep-check.yml` | Phase 2 |

## Metrics

- Tasks: 50/50 ✓
- Commits on slice branch: ~30 (incremental per task group)
- PRs opened (signal): 1 (#22)
- PRs opened (noise): 10 (auto-bump bot, all closed at close-out)
- Playbook releases shipped during slice: 6 (rc1→rc6)
- CI iterations to green: 6 (initial fail → 5 cascading fixes)
- Local pre-commit iterations: many (each commit ran the full hook chain)

## References

- Slice plan: [docs/openspec-slice.md](../docs/openspec-slice.md) row 1
- Specs promoted: [openspec/specs/{monorepo-tooling,secrets-baseline,compliance-baseline}](../openspec/specs/)
- Archived change: [openspec/changes/archive/2026-05-01-bootstrap-monorepo/](../openspec/changes/archive/2026-05-01-bootstrap-monorepo/)
- Gate F approval: [docs/hitl-gates-log.md](../docs/hitl-gates-log.md) entry 2026-05-01
- Gotchas surfaced: [docs/gotchas.md](../docs/gotchas.md) entries 1-10
