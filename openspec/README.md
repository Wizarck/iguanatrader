---
type: openspec-root
project: iguanatrader
schema_version: 1
created: 2026-04-28
---

# OpenSpec — iguanatrader

OpenSpec implementation phase artefacts. Initialized 2026-04-28 post Gate C approval (see [docs/hitl-gates-log.md](../docs/hitl-gates-log.md)).

## Layout

- `changes/<slice-id>/` — active OpenSpec changes (one per slice from [docs/openspec-slice.md](../docs/openspec-slice.md)). Each contains `proposal.md` + `specs/<capability>/spec.md` + `design.md` + `tasks.md` per `.ai-playbook/specs/runbook-bmad-openspec.md` §3.1.
- `specs/` — archived spec capabilities (promoted via `/opsx:archive` after change is implemented + merged + retro completed). Hand-edits blocked by `.ai-playbook/scripts/block_manual_spec_edit.py`.
- `retros/<slice-id>.md` — post-archive retrospectives per slice + weekly + monthly per `.ai-playbook/specs/retrospective-cadence.md`.

## Active changes

(populated as `/opsx:propose <slice-id>` runs)

## Slice plan reference

See [docs/openspec-slice.md](../docs/openspec-slice.md) for the full 20-change catalogue with dependency graph + waves (canonical schema per `.ai-playbook/specs/bmad-openspec-bridge.md` §3.1).

## Workflow

Per `.ai-playbook/specs/runbook-bmad-openspec.md` §3:

1. `/opsx:propose <slice-id>` → drafts proposal.md (QA: Blind Hunter + Acceptance Auditor)
2. `specs/*.md` || `design.md` (QA: Edge Case Hunter + Acceptance Auditor + Blind Hunter)
3. `tasks.md` (QA: Acceptance Auditor)
4. Human approval (Gate E) + `/opsx:apply <slice-id>` → implementation in `slice/<id>` branch
5. PR review + CI green + Gate F human approval
6. `/opsx:archive <slice-id>` → promotes to `openspec/specs/`, drafts `retros/<slice-id>.md`

Verdicts use `.ai-playbook/specs/verdict-contract.md` (✅/⚠️/❓ literals + S1-S4 severity rubric).
