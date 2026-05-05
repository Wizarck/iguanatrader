# Retrospective: api-foundation-rfc7807

- **Archived**: 2026-05-05
- **Archive path**: openspec/changes/archive/2026-05-05-api-foundation-rfc7807/
- **Schema**: spec-driven
- **PR**: #67 (admin-merged 2026-05-05, commit `fd874f4`)

## What worked

The **anti-collision foundation pattern** landed exactly as designed: every Wave-2 slice (R1 research-schema, T1 trading-models, K1 risk-engine, P1 approval-channels, O1 observability-cost, W1 dashboard-skeleton) can now add `routes/<name>.py` / `sse/<name>.py` / `cli/<name>.py` files **without** editing `app.py` or `cli/main.py`. The contract is small, mechanically obvious from `pkgutil.iter_modules`, and the tests in `test_dynamic_discovery.py` lock it in. Slice 5 was foundation-only by design (no concrete routes), so the contract has no integration burden yet — Wave 2 will be the first real exercise.

The **global RFC 7807 handler chain** collapsed slice 4's `_problem_response` helper into one place. The slice-4 surface (3 endpoints) was small enough that the helper looked OK; for Wave 1+ adding 5+ routes per slice, having every route just `raise IguanaError(...)` instead of remembering to wrap in `JSONResponse(...)` is materially cleaner. The structlog `<context>.<entity>.<action>` event-name convention extended naturally to `api.router.{registered,skipped,import_failed}` and `api.unhandled_exception`.

The **OpenAPI → TypeScript typegen pipeline** wired in CI as a bot-commit pattern (mirroring `regenerate-lock.yml`) means Slice W1+ will get a typed client *automatically* on every push that changes the OpenAPI surface. No drift-by-construction. The `pnpm typegen:from-running-api` script is the dev-mode mirror — same pipeline shape, sourced from a manually-running uvicorn instead of one CI booted itself.

Local smoke (`create_app()` boots, dynamic discovery registers the 3 auth routes, CLI `--version` prints the version string) caught the slice-design-time logic clean before push. CI iteration was minimal: one mypy fix (missing return-type annotation on a test fixture) + one workflow fix (missing `PYTHONPATH` for uvicorn). Total CI cycles: 2.

## What didn't

Local pytest hung on `iguanatrader.persistence` import (same Windows quirk slice 4 hit). The pattern of "writing tests locally, smoke-testing the source paths, pushing to CI for the canonical exerciser" is now the de-facto endgame for Wave 0 slices on this Windows venv. Slice O1 follow-up: get `poetry install` working locally so pytest doesn't depend on CI.

The `# noqa: B008` on `cli/main.py::_root_callback` was removed after recheck because ruff doesn't actually flag `typer.Option(...)` as B008 — the suppression was unnecessary defensive code. Useful reminder: **ruff config evolves, suppressions drift**. The `extend-immutable-calls` list in `pyproject.toml` already covers FastAPI factories; Typer's `Option` is recognized via a different ruff heuristic (probably `_TyperOption` not matching the immutability check). Either way, recheck `# noqa` directives at every slice — RUF100 catches dead suppressions.

The L2 CodeRabbit fallback's `ai-self-review-required` check requires three exact substring markers (`Profile:`, `Reviewer:`, `Self-review findings:`) in the PR body §4.5 section. My initial PR body had a §4.5 header but used different field names ("Self-review against this PR's diff focused on..."). Required a second body edit + manual L2 workflow re-run to flip the check. Ergonomic gap: the playbook contract should be discoverable from the workflow file itself (or a CI annotation pointing at the script's expected schema). Slice O1 candidate: surface the marker schema in the §4.5 stub the worker AI should fill, so future slices don't drift.

The slice-3 listener `tenant_id_var` raise behavior (gotcha #28 from slice 4) is **still** the bootstrap-path footgun. Slice 5 didn't try to fix it — out of scope — but every slice that adds a bootstrap-path query (e.g., the future T4 `bootstrap-tenant` CLI) will have to re-discover the raw-SQL bypass workaround. Slice O1 carry-forward.

## Lessons

- **Foundation slices have no obvious test surface** — slice 5 is mostly "the dynamic-discovery loop works" and "the global handler renders RFC 7807." Both are mechanically simple; the value isn't algorithmic correctness, it's the **ergonomic contract** for downstream slices. Tests focus on: "can a Wave-1 slice add a route module without touching `app.py`?" (yes, integration test drops a stub) + "does a broken module fail boot loudly instead of silently disappearing?" (yes, the discovery loop re-raises). Worth thinking about test design as "what contract does the next slice expect" not "did this code do its job."
- **`Exception` fallback handlers in FastAPI MUST re-raise framework exceptions** — gotcha #30. The `(HTTPException, RequestValidationError)` re-raise inside `_render_internal` is the difference between FastAPI's native 404/422 surviving and getting clobbered into 500 + Problem. Easy to forget; locked in by two integration tests.
- **`package-mode = false` requires `PYTHONPATH` for uvicorn** — pytest reads `pythonpath` from `pyproject.toml`'s `[tool.pytest.ini_options]`, but uvicorn doesn't. Any future workflow that boots the FastAPI app in CI MUST set `PYTHONPATH: apps/api/src` in the env block. Worth a gotcha entry someday but not yet (slice 5 is the only such workflow).
- **CodeRabbit Profile A actually completed for this PR** (slice 4 had Profile B fallback both times). The free-tier quota apparently reset; or the diff was small enough that the primary review queue picked it up faster. Either way, Profile A is achievable and the workflow shape is the same.
- **Bot commits before slice work pushes**: the `regenerate-lock.yml` workflow auto-fires on `pyproject.toml` changes. Slice 5's first push triggered it; the bot commit landed on the slice branch before my second push, requiring a `git pull --rebase` to integrate. The pattern: push slice work → CI bot pushes lock regen → next local push needs rebase. Minor friction; not worth automating away.
- **The `# noqa: B008` reflex on Typer/FastAPI factories should be skeptical**, not automatic. Ruff knows about FastAPI's factories via `extend-immutable-calls`; Typer's `Option` is fine without explicit allowlisting. Verify with a recheck pass before adding the suppression.

## Carry-forward to next change

- **Slice O1 (observability + boundary hardening) — open items:**
  - Fix slice-3 listener `_inject_tenant_filter` to skip filter injection for queries that only touch non-scoped tables. Allows bootstrap-path helpers to collapse back to ORM (gotcha #28 + slice 5 routes/auth.py raw-SQL bypass).
  - Boot-time guard rejecting `IGUANATRADER_DEV_INSECURE_COOKIE=1` when `IGUANATRADER_ENV=production` (slice 4 carry-forward; not addressed in slice 5).
  - Linter / pre-commit rule flagging ORM SELECT inside `get_current_user` (defends gotcha #28's contract).
  - Auto-rehash Argon2 on login when stored hash params below current env settings (slice 4 carry-forward).
  - Add `--cov-fail-under=80` to the CI pytest invocation so coverage threshold is enforced, not just measured.
  - Get `poetry install` working on Arturo's Windows venv (or document the alternative — e.g. pip-install pattern) so local pytest doesn't depend on CI.
  - Surface the L2 §4.5 marker schema (`Profile:` / `Reviewer:` / `Self-review findings:`) in a discoverable place — either as a CI annotation pointing at the playbook script, or as a stub the worker AI fills.
- **Slice T4 (`bootstrap-tenant` CLI):** first concrete consumer of the `cli/<name>.py` auto-discovery scaffold from slice 5. Will validate the contract end-to-end (a slice adds a file, no edits to `cli/main.py`, the subcommand appears in `--help` automatically). Lazy-import contract from gotcha #29 applies — bootstrap-tenant will need SQLAlchemy + Argon2 inside the command body, not at module scope.
- **Slice W1 (`dashboard-svelte-skeleton`):** first concrete consumer of `@iguanatrader/shared-types`. Will exercise: (a) the workspace symlink resolves at type-check time, (b) the openapi-types CI bot commit lands the regenerated `index.ts` before W1's first push, (c) `import { Problem } from '@iguanatrader/shared-types'` resolves and the type matches the actual error body shape. If any of these fail, the slice 5 contract has a hole; document + fix in slice O1 if so.
- **Wave 2 routes (R1 / T1 / K1 / P1 / O1):** will be the first time multiple slices land in parallel via the dynamic-discovery contract. Worth tracking: are the `routes/<name>.py` files genuinely orthogonal? (i.e., zero merge conflicts when the slices' branches all rebase to main). If conflicts surface, what was missed in the slice 5 design?
- **Lighthouse threshold bump in slice W1:** slice 5 set a11y ≥ 90 as the only hard gate (perf / best-practices / seo informational). Slice W1 may bump a11y to ≥ 95 once the dashboard surface stabilises; that's a slice W1 decision, not a slice 5 retrofit.
