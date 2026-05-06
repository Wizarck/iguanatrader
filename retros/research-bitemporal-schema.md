# Retrospective: research-bitemporal-schema

- **Archived**: 2026-05-06 (post-hoc; PR merged 2026-05-05)
- **PR**: [#68](https://github.com/Wizarck/iguanatrader/pull/68)
- **Squash SHA**: see PR #68 mergeCommit
- **Archive path**: `openspec/changes/archive/2026-05-06-research-bitemporal-schema/`
- **Schema**: spec-driven
- **Tasks**: 37/37 (100%)

## What worked

- Bitemporal facts table + provenance model landed cleanly per design.md. The `valid_from` / `valid_to` + `as_of` two-axis model survived integration with downstream slices.
- 37/37 tasks ticked at apply time — disciplined commit-per-group cadence kept tasks.md aligned with reality.

## What didn't

- **Silent board drift** — PR merged 2026-05-05 23:10 UTC but the project board never transitioned `Blocked → In Progress → Review → Done`. Stayed at `Blocked` until 2026-05-06 board-fix sweep. Same drift hit K1, P1, O1, W1, T1.
- **Archive never run** — `openspec/changes/research-bitemporal-schema/` sat in the active tree post-merge for ~28 hours. Surfaced when v0.10.0's `verify_board_state.py` was first invoked (which itself failed initially due to the pagination bug fixed in v0.10.1).

## Lessons

- The L1/L2 server-side workflows from project-board-sync.md (v0.10.0) would have caught the board drift at PR-open time. Wire those in iguanatrader as part of v0.10.0 adoption.
- `openspec archive` skill needs an automated post-merge invocation, not a manual one. Candidate: a workflow that runs `openspec archive` on slice/* branch merge.

## Carry-forward to next change

- v0.10.2 ai-playbook: scaffold `propagate-archive.yml` workflow template that runs `openspec archive --change <id>` when a slice/<id> PR squash-merges to main. Closes the silent-archive-drift gap surfaced here.
- v0.10.0 L2 (`project-board-synced-check.yml`) needs to be installed in iguanatrader so future Wave 3+ slices fail-loud at PR-open if board not in sync.
