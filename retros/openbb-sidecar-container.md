# Retrospective: openbb-sidecar-container (R4)

- **Archived**: 2026-05-06
- **PR**: [#82](https://github.com/Wizarck/iguanatrader/pull/82)
- **Squash SHA**: see PR #82 mergeCommit
- **Archive path**: `openspec/changes/archive/2026-05-06-openbb-sidecar-container/`
- **Schema**: spec-driven
- **Tasks**: 8 groups; ~60 sub-tasks; ~30% completed `[~]` deferred to future slices
- **Lines shipped**: ~1300 lines (sidecar code + monolith client + Helm-revert + docs + 23 tests)

## What worked

- **Forward-authored retro pattern** (per ai-playbook v0.10.0): scaffolded the proposal/design/tasks via parallel subagents in PR #79 first; this slice's apply phase consumed those pre-written artifacts as the spec contract. Reduced "what should this slice do?" friction to zero.
- **3-surface CI gate** for the AGPL boundary (declared dep + resolved dep + source imports + yfinance ban) is hard-blocking and orchestrator-agnostic. License-boundary protection is not coupled to which container runtime hosts the sidecar.
- **Helm revert was the right call**. Initial pivot from compose → k8s+Fleet was driven by user's Rancher correction; second pivot back to compose-only came from peer-AI feedback that k8s is for prod/staging apps that serve traffic, not mid-development infra. Net result: cleaner slice, no premature abstraction, deployment-foundation slice will helmify everything together when it's time.
- **Lazy openbb import + `/health` never-5xx contract** kept cold-start fast and isolated openbb breakage to readiness rather than liveness. Operationally the right pattern.
- **Subagent in PR #79 caught two of my prompt mistakes** before I noticed them (port 8765 vs 8001; pit_class column name vs tier). Worth letting subagents cite their canonical sources back at the prompt.

## What didn't

- **CI feedback loop took 4 rounds** to converge: `git diff --quiet` bug in lock workflow → ruff F401s → mypy duplicate-tests + no-any-return → black format. Each round cost ~5 min of CI time. Lesson: run `python -m ruff check && python -m ruff format --check && python -m black --check && python -m mypy --strict` locally on EVERY changed file before pushing, not "after I think I'm done".
- **Premature Helm chart shipped + reverted** wasted ~250 lines of YAML work. Lesson: when scope shifts mid-slice, pause to re-anchor on "what does this slice actually need to ship?" rather than expanding to cover the corrected anchor's full implications.
- **Workflow bug shipped** (`git diff --quiet` doesn't see untracked files): tests for the workflow itself didn't exist; the bug only surfaced on first invocation against a brand-new lock target. Lesson: any one-shot CI workflow with file-creation behavior needs a "first-run smoke" path.
- **HeartbeatMixin assumption mismatch**: design.md claimed the mixin would apply, but the mixin is async-only and `SourcePort.fetch` is sync. Honest deviation noted in code + tasks, but the design.md was wrong from the start (subagent in #79 didn't catch the async/sync mismatch).
- **Many `[~]` deferrals** (3.5, 4.5, 4.6, 5.6, 6.3, 7.2-7.4, 8.4-8.7, 8.9): each one honestly named WHY it's deferred but the cumulative effect is "this slice is 70% done, not 100%". The remaining 30% is verification-class work that needs runtime (Docker build, live openbb SDK, sidecar-live pytest job in CI).

## Lessons

- **Local lint+format pass is non-negotiable before push**. Adding to my workflow: `make lint-changed-files` shortcut that runs ruff + black + mypy on the diff vs origin/main.
- **Scope correction = pause, don't expand**. When user says "actually our infra is X", first reduce scope to "what does THIS slice still need" (often: less, not more), then ship.
- **Validation against canonical docs is real value-add from subagents**. PR #79 subagent grounded port number and column name from authoritative repo files; my prompt had both wrong. Future subagent invocations should explicitly ask "validate every literal name/value against the canonical doc" as a step.
- **Async-vs-sync interface contracts** need explicit verification in proposal phase, not at apply time. Add to openspec-propose skill: when proposal references a Protocol from a prior slice, re-read that Protocol's signature and confirm async/sync compatibility with the proposed adapter shape.
- **Lock-file workflow needs first-run validation**. Future workflow tweaks: include a paired test branch that exercises both "lock exists, no diff" and "lock missing, must create" paths.

## Carry-forward to next change

- **`deployment-foundation` slice** (future, post-Wave-3): helmify all components together (api + openbb-sidecar + litestream + frontend) following `eligia-core/helm/eligia-stack/` pattern. Resource caps + NetworkPolicy intent + non-root SecurityContext defaults preserved in `docs/architecture-decisions.md` §"OpenBB Sidecar Topology" for direct lift.
- **`sidecar-live` pytest marker + e2e test + CI sidecar-tests job** (R4 follow-up): tasks 7.2-7.4 + 8.7 deferred. Pairs with the future shared-primitives → api Dockerfile slice.
- **NEGATIVE license-boundary test branch** (R4 task 6.3 follow-up): paired-PR ritual with intentional `openbb` leak in `apps/api/pyproject.toml` to confirm the gate fails red. ~30 min of work, can land any time.
- **ai-playbook spec follow-up**: lock-workflow first-run smoke pattern (the `git diff --quiet` bug). Add to v0.11.0 release-management.md §6 lessons.
- **R5 `research-brief-synthesis`** can now use `OpenBBSidecarSource` + `YFinanceProxySource` from this slice to build the synthesis layer's input bundle; mocks no longer needed for those two sources.
