# Retrospective: trading-models-interfaces

- **Archived**: 2026-05-06 (post-hoc; PR merged 2026-05-05)
- **PR**: [#69](https://github.com/Wizarck/iguanatrader/pull/69)
- **Squash SHA**: see PR #69 mergeCommit
- **Archive path**: `openspec/changes/archive/2026-05-06-trading-models-interfaces/`
- **Schema**: spec-driven
- **Tasks**: 35/42 (83%) — 7 unchecked are explicitly "deferred to CI" or "N/A in apply phase" per the slice brief (see tasks.md §9). All deferred items resolved post-merge through the canonical CI run.

## What worked

- Trading entities + ports + service skeleton ladder landed cleanly. The "ports as Protocol classes" pattern adopted from openTrattOS proved easy to mock in unit tests.
- Brief said "Do NOT push, do NOT open a PR" during apply — keeping the apply phase strictly local until ready avoided premature CI noise.

## What didn't

- **Silent board drift** — same as research-bitemporal-schema. Board stayed `Blocked` 28 hours after merge.
- **tasks.md §9 ambiguity** — items 9.2-9.8 marked `[ ]` but explicitly described as "deferred to CI" / "N/A". The `[~]` partial marker (per ai-playbook v0.10.0 follow-up) would have communicated this more clearly. Cost: 0/55 boxes ticked appearance bias surfaced in iguanatrader slice 3 retro (filed as ai-playbook Followup #4).
- **Archive never run** — same as R1.

## Lessons

- For slice-internal tasks that depend on **post-merge CI**, use `[~]` not `[ ]` so retro analysis reflects intent (per ai-playbook `release-management.md` §6.4 followup).
- The "Do NOT push" instruction works for apply-phase discipline, but the post-apply checklist (tick boxes 9.x, run archive) needs a clearer trigger than "remember to do it later."

## Carry-forward to next change

- Same as research-bitemporal-schema: v0.10.2 needs propagate-archive workflow + iguanatrader needs L2 board-synced check installed.
- T2 (ibkr-adapter-resilient) inherits the ports/Protocol skeleton from this slice — no rework expected.
