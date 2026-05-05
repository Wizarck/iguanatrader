# Retrospective: shared-primitives

- **Archived**: 2026-05-05 (post-hoc; slice merged 2026-05-01)
- **Archive path**: openspec/changes/archive/2026-05-01-shared-primitives/
- **Schema**: spec-driven
- **PR**: #41 (squash-merged 2026-05-01, commit `2124428`)

## Note on this retro

Slice 2 was implemented in a prior session. This retro is a post-hoc Gate F closure when the openspec change folder was archived alongside slice 4 hygiene cleanup on 2026-05-05. The substantive lessons are scattered across the design.md and the implementation diff; this stub captures only the closure-level facts so future readers know the slice IS Gate-F-complete.

## What worked

The shared kernel package (`iguanatrader.shared`) became the load-bearing primitive layer for every subsequent slice — slice 3 (persistence) imports `tenant_id_var` + `with_tenant_context`; slice 4 (auth) imports `IguanaError` hierarchy + `time.utc_now` + `hash_password` builds on top of the structlog event-name convention; future slices T4 (trading), R5 (research), K1 (risk) will import `Money`, `backoff_seconds`, `HeartbeatMixin`, `BaseRepository`, `Port` Protocol root.

The "stdlib-only, zero domain knowledge, zero imports from `iguanatrader.contexts`/`api`/`persistence`/`cli`" boundary has held — the pre-commit hook that enforces it has not had to fire in subsequent slices, suggesting the constraint is intuitive.

The Hypothesis property tests (decimal arithmetic, backoff monotonicity, message ordering, heartbeat idempotency) caught at least one subtle bug during initial development per the slice notes (per Arturo).

## What didn't

(Not captured here — the slice's own working notes / commit history are the canonical record.)

## Lessons

(Implicit; see slice 4's retro for the cascading consequences of slice-3's listener design having a documented behaviour that didn't match implementation — slice 2 set the structlog convention slice 3 + 4 follow.)

## Carry-forward to next change

Already absorbed into subsequent slices (3, 4) and the project's gotchas file. No outstanding action items from this slice itself.
