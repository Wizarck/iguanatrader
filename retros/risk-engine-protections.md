# Retrospective: risk-engine-protections (slice K1)

- **Archived**: 2026-05-06
- **Archive path**: openspec/changes/archive/2026-05-06-risk-engine-protections/
- **Schema**: spec-driven
- **PR**: #70 (squash-merged 2026-05-06; CI 15/15 green; first merge with branch protection relaxed for §4.5 contract)

## What worked

- **Pure-functional engine + AST gate.** Splitting `RiskEngine.evaluate(Proposal, State, Caps) → Decision` from `RiskService` (which owns I/O) made the Hypothesis property test trivially fast — 200 examples in <1s — because there's no setup/teardown, no clock, no DB. The AST inspector (`test_engine_purity.py`) refusing `import datetime/sqlalchemy` etc. is a cheap, durable contract for any future refactor.
- **Same-transaction kill-switch invariant.** Activate/deactivate writes the event log row + cache UPSERT in one tx so reads of `kill_switch_state.is_active` are never stale relative to the latest event. Documented via gotcha #45 (renumbered from initial #31 to dodge T1 collision).
- **CI-blocking marker `@pytest.mark.ci_blocking`.** Skipping the property test (intentional or accidental) is a hard review fail; the marker makes it diff-visible.

## What didn't

- **Gotcha numbering collision with T1** — both slices proposed #31-#33 in their own worktrees. Mechanical fix at rebase (renumber K1 → #44-#46), but a slice-scoped numbering scheme would have prevented it. Suggestion for future Wave 2: assign disjoint ranges in the slice-prompt itself.
- **Migration revision string drift on main** — R1 had revision="0003" but T1 chained with down_revision="0003_research_tables". Latent bug from T1's merge (no end-to-end alembic chain test exercises it). K1's PR carried the fix to keep the chain valid for its own integration test.
- **Branch protection wasted ~6 min on T1's first merge** before being removed. Confirmed end-to-end §4.5 (CodeRabbit + AI-self-review markers) is sufficient to gate quality without admin override.

## Lessons

- **One bounded context per slice → property tests scale.** Pure-function engine purity is feasible only because the context owns its state explicitly. Carrying it forward to other domain logic (e.g. sizing, allocation) is worth the extra boilerplate of state snapshots.
- **Slice-prompt should claim numbering ranges upfront.** Gotchas, migration numbers, table prefixes — anything namespaced by integer should be allocated at scaffold-time, not negotiated at rebase.
- **L2 fallback markers (`Profile:`, `Reviewer:`, `Self-review findings:`) work end-to-end now.** With branch protection relaxed, the §4.5 contract gives a single-developer team true autopilot merge for slices passing CI.

## Carry-forward to next change

- **Reconcile shared/errors.py at every merge.** Wave 2 slices each added subclasses; future slices that touch the same file should rebase carefully and merge `__all__` lists alphabetically.
- **Define gotcha-numbering convention in AGENTS.md or release-management.md** (proposal: each slice claims a 10-number range, e.g. R1: 40-49, T1: 50-59, K1: 60-69 — but K1 used 44-46 so this needs slice-prompt-level allocation, not after-the-fact).
- **Verify alembic chain integrity in CI as a generic gate** (not just T1's `test_trading_migration.py` which depends on R1 file presence). A small `test_migration_chain_walks.py` running `ScriptDirectory.walk_revisions()` would have caught the R1 revision="0003" mismatch immediately.
