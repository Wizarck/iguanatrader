# Retrospective: test-cookies-pattern-migration

- **PR**: [#152](https://github.com/Wizarck/iguanatrader/pull/152) (merged 2026-05-14, squash `7f44106`).
- **Archive path**: `openspec/changes/archive/2026-05-14-test-cookies-pattern-migration/`
- **Lines shipped**: 69 insertions / 51 deletions across 5 files. CI 15/15 green after AI-reviewer signoff fix.

## What worked

- **Pure mechanical sweep, ~8min agent wall-time** — 45 call sites across 5 files migrated to canonical `client.cookies.set(COOKIE_NAME, cookie)` pattern. Zero behavior change; assertions/seeds/fixtures untouched. `grep cookies={COOKIE_NAME` returns 0 post-migration.
- **Cross-tenant cookie swap handled correctly** — tests using `cookie_a` then `cookie_b` (e.g. `test_portfolio_isolated_across_tenants`) get a second `client.cookies.set()` immediately before the cross-tenant block. Overwrite semantics make this clean.
- **Promoted "nice to have" to "must do" based on 2nd hit** — PR #149 retro deferred this; PR #151 retro promoted it. Pattern: when the same latent issue blocks two consecutive slices, it stops being deferrable.

## What didn't

- **Agent's PR body missed the canonical `## AI-reviewer signoff` section** with the three required markers (`Profile:`, `Reviewer:`, `Self-review findings:`) per `.ai-playbook/specs/release-management.md §4.5.3`. Body had a substantive `## §4.5 self-review` section but the L2 fallback's regex looks for those exact marker strings. Fix: edit PR body to append the canonical block + `gh run rerun` the L2 workflow. **Pre-flag for agent prompts**: include the AI-reviewer signoff template verbatim. The "§4.5 self-review" naming the agent picked up from earlier PRs predates the v0.11.0+ schema gate.
- **Site count off-by-2 in proposal** — proposal claimed 23 sites in `test_portfolio_routes.py`; actual was 21. Minor; agent flagged it correctly in the report. Lesson: don't bother counting in the proposal — let the agent grep-validate and report.
- **L2 workflow takes ~5 min to re-run** — total time from "fix body" → "merge" was ~6 min, dominated by L2 cycle. Not a bug; just CI rhythm.

## Carry-forward

- **`authed_client` fixture abstraction** — hoisting `client.cookies.set(COOKIE_NAME, ...)` into a pytest fixture (`async def authed_client(...): client.cookies.set(...); yield client`) would eliminate the per-test setter. Deferred to v1.5 `test-fixtures-authed-client` if/when the pattern keeps proliferating across new test files. Current 9 files (4 already canonical + 5 migrated here) is manageable without the fixture.
- **Update agent-spawn template** to include the canonical `## AI-reviewer signoff` block with placeholders. Eliminates the L2 re-run cycle for future PRs.

## Pattern usage

- **AI-reviewer signoff section is REQUIRED, not optional** — even for trivial Profile B chores, the three markers must appear verbatim or `ai-self-review-required` check fails. Template:
  ```
  ## AI-reviewer signoff
  - **Profile**: B (mechanical chore; no semantic diff)
  - **Reviewer**: self-review (CodeRabbit L1 passed; no actionable comments expected)
  - **Self-review findings**: none — <one-sentence justification grounded in the diff shape>
  ```
- **Override `client.cookies.set` for multi-cookie tests** — setter overwrites cleanly; no need to delete or reset the jar. Cleaner than the kwarg-per-call pattern.
- **Two-hit rule for promoting deferred items** — if the same latent issue blocks consecutive slices, it stops being "nice to have". Document the promotion in the second retro.
- **STOP after gh pr create** — 4-for-4 across PRs #149/#150/#151/#152. Permanent template lock.
