---
schema: agents-md/v1
version: 0.1.0
inherits_from:
  - github.com/Wizarck/ai-playbook@v0.19.6
updated: 2026-05-25
project: iguanatrader
owner: arturo6ramirez@gmail.com
capabilities_map: true
# Tracker surface for change-tracking tickets (per docs/concepts/issue-tracking.md).
# Required by scripts/issue_sync.py. Pick one: github | jira.
#   github → opens issues against this repo on GitHub.
#   jira   → opens issues against `jira_project` (key below; required iff jira).
tracker_kind: github
# jira_project: PROJ
# personal: true   # uncomment for personal repos (always GH Issues regardless of tracker_kind)
---

# iguanatrader — AGENTS.md

> Project dispatcher. Lean file. Universal norms inherit from `.ai-playbook/specs/*` (pinned via `inherits_from` above).

## 0 Bootstrap directive

Before responding to ANY task:

1. Read `.ai-playbook/specs/dispatcher-chain.md` — universal norms inherited from the pinned playbook tag.
2. Read `.ai-playbook/specs/release-management.md` — branch model, PR shape, CI gates. Critical sections: **§4.5 AI-reviewer feedback loop** (must read CodeRabbit / claude-code-action comments before Gate F), **§5.6 Profile A/B** (visibility-driven enforcement), **§6.5 pre-flight rebase** (run `opsx_apply_companion.py` before first task commit).
3. Consult `.claude/injected-context.md` — populated by the SessionStart hook from `hindsight.recall(query="iguanatrader <topic>")` against bank `iguanatrader`. If absent or showing `DEGRADED_CONTEXT`, announce + proceed without prior recall.
4. Check `openspec/changes/*/` for active work on the topic. If a change is live, extend it — don't start parallel work.
5. Only then respond.

## 1 Project identity

{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}

## 2 Dispatcher index

| Topic | Pointer |
|---|---|
| **How to make a change in this project (canonical entry point)** | [.ai-playbook/docs/development-flow.md](.ai-playbook/docs/development-flow.md) |
| Daily-dev runbook | [docs/runbook.md](docs/runbook.md) |
| Architecture decisions | `docs/architecture-decisions.md` *(create when first ADR lands)* |
| PRD | `docs/prd.md` *(create when product brief lands)* |
| Universal playbook norms | [.ai-playbook/specs/](.ai-playbook/specs/) |
| Verdict + severity contract | [.ai-playbook/specs/verdict-contract.md](.ai-playbook/specs/verdict-contract.md) |
| Memory hierarchy + retain CLI | [.ai-playbook/specs/memory-hierarchy.md](.ai-playbook/specs/memory-hierarchy.md) |
| Hindsight retain runbook | [.ai-playbook/runbooks/hindsight-retain.md](.ai-playbook/runbooks/hindsight-retain.md) |
| Branch / PR / release lifecycle | [.ai-playbook/specs/release-management.md](.ai-playbook/specs/release-management.md) |
| Merge style decision rules | [.ai-playbook/specs/merge-policy.md](.ai-playbook/specs/merge-policy.md) |
| Conflict resolution between parallel PRs | [.ai-playbook/specs/conflict-resolution-policy.md](.ai-playbook/specs/conflict-resolution-policy.md) |

## 3 Active work

{{ACTIVE_OPENSPEC_CHANGE_OR_NONE}}

## 4 Project hard rules (project-specific, NOT duplicating playbook)

{{PROJECT_SPECIFIC_RULES_NOT_DUPLICATING_PLAYBOOK}}

## 5 Capability map

| Need | Tool / skill | Where |
|---|---|---|
| Recall prior decisions | `python .ai-playbook/scripts/inject_context.py --bank-id iguanatrader` (auto-fired by SessionStart hook) | playbook |
| Retain a lesson / decision / gotcha | `python .ai-playbook/scripts/retain_memory.py --bank iguanatrader --kind <kind> --content "..." --why "..."` | playbook |
| OpenSpec ops | `/opsx:propose | apply | archive | explore` | `.claude/commands/` |
| Pre-flight before `/opsx:apply` (Branch+SHA capture + rebase, per release-management.md §6.5) | `python .ai-playbook/scripts/opsx_apply_companion.py --change-id <slice> --owner Wizarck --project-number <N> --repo Wizarck/iguanatrader` | playbook |
| Validate OpenSpec change | `python .ai-playbook/scripts/openspec_validate.py` | playbook |
| Validate this AGENTS.md | `python .ai-playbook/scripts/schema_validate.py AGENTS.md` | playbook |
| Bootstrap / re-bootstrap GH Project board (Profile A/B) | `python .ai-playbook/scripts/bootstrap_gh_project.py --owner Wizarck --project-number <N> --repo Wizarck/iguanatrader --profile auto` | playbook |
| Auto-transition Blocked → Todo on dep merge | `python .ai-playbook/scripts/auto_transition_blocked_todo.py --owner Wizarck --project-number <N>` (also wired via `.github/workflows/project-status.yml`) | playbook |
| Hard dep-graph check at PR merge time | `python .ai-playbook/scripts/check_slice_dependencies.py --owner Wizarck --project-number <N> --change-id <slice>` (also wired via `.github/workflows/dep-check.yml`) | playbook |
| Render MCP configs | `python .ai-playbook/scripts/mcp/render.py --project iguanatrader` | playbook |
| Secrets scan | `python .ai-playbook/scripts/secrets_scan.py` | playbook |
| Check for legacy↔v1 mcp-servers drift | `python .ai-playbook/scripts/check_mcp_drift.py` | playbook |

## 6 MCP sources (SSOT pointer)

3-layer SSOT per [.ai-playbook/specs/mcp-servers-schema.md](.ai-playbook/specs/mcp-servers-schema.md):

1. **Base** — `.ai-playbook/mcp-servers-base.yaml` (universal templates).
2. **Project** — [`mcp-servers.project.yaml`](mcp-servers.project.yaml) (this project's overrides + Hindsight bank `iguanatrader`).
3. **Personal** — `~/.config/mcp-servers.yaml` (per-dev tenant instances; never committed).

Rendered to [`.mcp.json`](.mcp.json) + [`.gemini/settings.json`](.gemini/settings.json) via `scripts/mcp/render.py`. Regenerate after editing the project layer.

## 7 Overrides inherited from playbook

{{NONE_OR_EXPLICIT_OVERRIDES_WITH_RATIONALE}}

<!--
If this project has a pre-existing OpenSpec custom workflow (its own
`openspec/schemas/<name>/schema.yaml` with N artefacts), use the **fusion
integration pattern** to import playbook contracts without replacing the
custom workflow. See [.ai-playbook/specs/fusion-integration-pattern.md].

Typical §7 sub-sections for fusion projects:
  §7.1 — OpenSpec workflow (fusion, not replacement) + verdict mapping
  §7.2 — Memory (dual canonical: openspec/memory.md + Hindsight bank)
  §7.3 — BMAD Discovery (skills available, workflow not mandatory)
  §7.4 — Available but not active by default (opt-in)
  §7.5 — Not applicable to this project

`scripts/drift_check.py --check overrides` validates that each entry cites
a playbook spec by path.
-->


## 8 Gotchas

{{EMPTY_FILL_AS_YOU_LEARN}}

Append one-line dated entries when a project gotcha is discovered:

```
- YYYY-MM-DD — <what went wrong>. <rule to apply next time>.
```

Promote recurring gotchas to Hindsight via `retain_memory.py --kind gotcha` so other sessions and projects benefit.

<!-- BEGIN auto-managed: caveman/ruleset:full -->
**Caveman mode: ON · intensity full**

Core rules:
- Drop articles (a/an/the), filler (just/really/basically), pleasantries, hedging.
- Fragments OK. Short synonyms. Technical terms exact. Code unchanged.
- Pattern: `[thing] [action] [reason]. [next step].`
- Not: "Sure! I'd be happy to help you with that."
- Yes: "Bug in auth middleware. Fix:"

Mode (full):
Drop articles. Fragments OK. Short synonyms. Technical terms exact. Code unchanged. Pattern: `[thing] [action] [reason]. [next step].` Default mode — about 65% output reduction.

Auto-clarity exceptions:
Drop caveman mode and use normal prose when:
- **Security warnings** — full sentences so the user does not misread risk.
- **Irreversible action confirmations** — `rm -rf`, `git push --force`, drop database, force-merge, etc.
- **Multi-step sequences** where fragment ambiguity could cause skipped or misordered steps.
- **User confused or repeating a question** — they need clearer, not shorter.

Resume caveman mode on the next turn.

Boundaries:
- Code, fenced code blocks, and tool inputs written normally — caveman applies to prose around them, not to code.
- Commit messages and PR descriptions written normally unless the user opts into `caveman-commit` or `caveman-review` skills.
- Comments inside generated code written normally.
- File paths, URLs, and identifiers preserved byte-for-byte.

Toggle off: `python -m scripts.caveman off`. Full rule: [skills/caveman/SKILL.md](skills/caveman/SKILL.md).
<!-- END auto-managed -->
