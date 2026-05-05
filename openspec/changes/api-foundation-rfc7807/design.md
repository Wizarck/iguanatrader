## Context

Slice 5 plants the **anti-collision foundation** that every Wave-1+ slice depends on. Wave 0 sequential foundation cumulative state at slice-5 start:

- Slice 1 `bootstrap-monorepo` ✅ — pnpm workspace, Makefile root, CI baseline, license-boundary check.
- Slice 2 `shared-primitives` ✅ — `IguanaError` hierarchy + `to_problem_dict()` method (consumed by slice 5's exception handler), `time.utc_now`, `tenant_id_var`, `Money`, `BaseRepository`, `Port`.
- Slice 3 `persistence-tenant-enforcement` ✅ — SQLAlchemy + Alembic + `tenant_listener`. Bootstrap raw-SQL bypass is a known footgun (gotcha #28); slice O1 will fix.
- Slice 4 `auth-jwt-cookie` ✅ — FastAPI app factory + auth surface + SvelteKit scaffold. Manual `app.include_router(auth_router)` flagged as slice-5 follow-up. `_problem_response` helper builds RFC 7807 by hand; slice 5 collapses to global exception handler.

The challenge is **structural, not algorithmic**. Wave 1 (R1, T1, K1, P1, O1) has 5 changes meant to land in parallel via worktree isolation. If each change had to edit `app.py` to register its router, there's no way to merge 5 PRs without serial conflict resolution. The dynamic-discovery pattern (`pkgutil.iter_modules` over `iguanatrader.api.routes`) is what makes Wave 1 parallel-safe — each PR adds a new file, none edits a shared file. Same logic applies to SSE (`api.sse`) and CLI (`cli/`).

The OpenAPI typegen pipeline closes the loop on the SvelteKit side: instead of duplicating Pydantic DTOs as TypeScript interfaces by hand, slice W1+ imports `@iguanatrader/shared-types` and gets a regenerated, semver-versioned client. Drift-by-construction is impossible — pre-commit regenerates the lockstep.

## Goals / Non-Goals

**Goals:**
- Plant the dynamic-discovery contract for routes / SSE / CLI so Wave 1+ slices add files without editing shared `app.py` / `cli/main.py`.
- Centralize the `IguanaError → RFC 7807` rendering in a single FastAPI exception handler so route handlers express errors via `raise` rather than hand-built `JSONResponse`.
- Wire the OpenAPI → TypeScript typegen pipeline end-to-end: CI generates `packages/shared-types/src/index.ts` from the live `/openapi.json`; pre-commit fails if the generated artefact is stale relative to the OpenAPI surface.
- Bootstrap the `packages/shared-types/` workspace package so `apps/web/` (slice W1+) can import via `@iguanatrader/shared-types`.
- Add Lighthouse CI step (per the original slice contract) for accessibility / performance baseline tracking on the SvelteKit dev server.

**Non-Goals:**
- No new routes (every concrete route family lives in its own slice; slice 5 is foundation-only).
- No SvelteKit-side consumption of `@iguanatrader/shared-types` — slice W1 (`dashboard-svelte-skeleton`) does the actual import + replacement.
- No `bootstrap-tenant` CLI subcommand — slice T4 ships that; slice 5 just plants the auto-discovery scaffold + an empty `cli/__init__.py`.
- No GraphQL surface, no gRPC, no protobuf — REST + RFC 7807 only.
- No `IguanaError` subclass additions (slice 2 fixed the hierarchy at 8 + `CurrencyMismatchError`); future contexts may add subclasses but slice 5 doesn't.

## Decisions

### D1. Dynamic discovery via `pkgutil.iter_modules` over package, NOT explicit registration list

**Decision**: `apps/api/src/iguanatrader/api/app.py` calls a single helper `_register_routers(app)` which iterates `pkgutil.iter_modules(iguanatrader.api.routes.__path__)`, imports each module, and `app.include_router(module.router, prefix="/api/v1")` for each module that exports a top-level `router: APIRouter`. Same pattern for SSE (`iguanatrader.api.sse`).

**Alternatives considered**:
- **Explicit list in `app.py`**: `app.include_router(auth_router); app.include_router(research_router); ...` — every slice edits `app.py`, every PR conflicts. Rejected.
- **`@app.include_router` decorator pattern at module level**: each `routes/<name>.py` calls `app.include_router(self_router)` at import time — requires the modules to import the global `app` instance, creating a circular import + breaking testability (each test would need a fresh app, but the module-level call would have already registered against the wrong app).
- **Explicit registry config file** (`routes.yaml` listing each module): config drift; new slices forget to add entries; harder to test.

**Rationale**: `pkgutil.iter_modules` is stdlib + zero-config + deterministic order (alphabetical by module name). The contract is "add a `routes/<name>.py` exporting `router: APIRouter`; the rest is automatic."

**Discoverability rule**: each route module MUST export a top-level `router: APIRouter`. The discovery loop logs a warning (structlog `api.router.skipped`) and skips modules that don't — so a typo in the variable name doesn't silently disable a route family.

### D2. SSE and CLI use the same dynamic-discovery shape — even though they don't have the same write-collision pressure

**Decision**: `apps/api/src/iguanatrader/api/sse/__init__.py` and `apps/api/src/iguanatrader/cli/main.py` apply the same `pkgutil.iter_modules` pattern as routes. SSE modules export `router: APIRouter` (FastAPI's SSE support is just a regular APIRouter that yields `StreamingResponse`); CLI modules export `app: typer.Typer` which the main CLI app `add_typer`s.

**Alternatives considered**:
- **Manual SSE registration** (it's a small surface area): same anti-collision logic still applies — the approval channel SSE (slice P1) and the research stream SSE (slice R5) shouldn't both edit `sse/__init__.py`.
- **CLI: just use Typer's app.add_typer manually**: slice 5 would only have an empty CLI app; future slices (T4 bootstrap-tenant, O1 admin commands, etc.) would each add to `main.py`. Same write-collision pattern — out of scope to allow it.

**Rationale**: consistency. Anyone reading `app.py` sees the same `_discover_and_register(...)` shape three times for three different module trees, with one helper function applied uniformly.

### D3. Single global `IguanaError` exception handler renders RFC 7807, NOT per-route handler

**Decision**: `apps/api/src/iguanatrader/api/errors.py::register_error_handler(app)` calls `app.add_exception_handler(IguanaError, _render_problem)` once, where `_render_problem(request, exc)` returns `JSONResponse(content=exc.to_problem_dict(), status_code=exc.status, media_type="application/problem+json")`. Routes raise `AuthError(...)`, `ValidationError(...)`, etc.; the handler intercepts every `IguanaError` subclass.

**Alternatives considered**:
- **Per-handler factory** (`_problem_response(...)`): what slice 4 shipped. Each route returns a `JSONResponse` manually. Verbose, easy to drift.
- **Middleware-based rendering**: middlewares intercept response, check status code, replace body. Convoluted; FastAPI's exception handler is the canonical hook.
- **Pydantic `@error_handler` decorator pattern**: not a thing; FastAPI uses Starlette's `add_exception_handler`.

**Rationale**: the FastAPI / Starlette `add_exception_handler` is the documented integration point. Routes stay clean (`raise AuthError("...")` reads as intent); the handler is one ~10-line function; coverage is uniform across every endpoint without route author having to remember.

**Implementation note**: also register a fallback handler for `Exception` (not just `IguanaError`) that wraps any unhandled error as `InternalError` + emits structlog `api.unhandled_exception` event with `exc_info=True`. Per NFR-O8, no exception escapes without a structured log breadcrumb.

### D4. `Problem` Pydantic v2 model in `dtos/common.py` mirrors `to_problem_dict()` field-for-field

**Decision**: `apps/api/src/iguanatrader/api/dtos/common.py::Problem` is a Pydantic v2 `BaseModel` with fields `type: str`, `title: str`, `status: int`, `detail: str | None`, `instance: str | None`. The handler's `to_problem_dict()` output JSON-loads cleanly into this. The Problem model is what `openapi-typescript` will render as the TypeScript `Problem` interface so frontend code can type-narrow `if (response.problem.type === "urn:iguanatrader:error:auth") { ... }`.

**Alternatives considered**:
- **No Pydantic model** (just dict): the OpenAPI schema wouldn't have a `Problem` component, so `shared-types` couldn't generate the type. Rejected.
- **Inheritance per error type** (`AuthProblem`, `ValidationProblem`): redundant — the discriminating field is `type` URI, the rest is uniform. Frontend pattern-matches on `type` string.

**Rationale**: typed errors are typed. The cost of one Pydantic model is paid once; every frontend consumer benefits.

### D5. OpenAPI typegen runs in CI, NOT in pre-commit

**Decision**: the `.github/workflows/openapi-types.yml` workflow boots the FastAPI app on a CI runner (uvicorn background process), curls `/openapi.json`, runs `pnpm openapi-typescript /tmp/openapi.json -o packages/shared-types/src/index.ts`, and commits the diff back to the branch (via the same `regenerate-lock.yml` mechanism — workflow-bot commit on slice branches). Pre-commit only verifies the file is byte-identical to a fresh regeneration if Python is available locally; CI is the source of truth.

**Alternatives considered**:
- **Pre-commit only**: requires every dev to have a working Python venv + the API installable. Per gotcha #18 the local poetry path is fragile; CI is the only reliable boot environment today.
- **Pre-commit + CI redundant**: doubles the cost; CI is sufficient.
- **Manual regeneration ("just remember to run `pnpm typegen` before committing")**: drift guaranteed. Rejected.

**Rationale**: CI is the existing trusted bootstrap path. Slices that change the OpenAPI surface push their commits, the workflow regenerates the types in a bot commit, and the next push picks up the typed client. Same workflow shape as `regenerate-lock.yml` (bot commits the lockstep artefact).

**Trade-off**: a slice author can't preview the generated TS locally without a working Python env. Workaround: `pnpm typegen:from-running-api` script that hits a manually-running uvicorn. Documented in `apps/api/README.md`.

### D6. `packages/shared-types/` is a buildless TypeScript package — it ships `src/index.ts` directly, no `tsc` build step

**Decision**: `packages/shared-types/package.json` declares `"main": "src/index.ts"`, no `build` script. The SvelteKit `tsconfig.json` resolves the path via the workspace symlink and consumes the TypeScript source directly. `openapi-typescript` regenerates `src/index.ts` in CI.

**Alternatives considered**:
- **`tsc`-built distributable** (`dist/index.js` + `dist/index.d.ts`): adds a build step + cache-invalidation surface; SvelteKit's vite + svelte-check handle TS source directly via the workspace symlink.
- **Use `tsc --noEmit` only for type checking**: that's what slice W1 will do with svelte-check; `shared-types` itself doesn't need its own tsc invocation.

**Rationale**: SvelteKit + Vite resolve TS source files in workspace siblings transparently. The fewer build steps in the workspace, the less drift. If a real bundler is needed later (e.g., publishing to npm publicly), add it then.

### D7. Lighthouse CI runs on `pnpm dev`, NOT `pnpm preview` (production build)

**Decision**: the Lighthouse CI step in `.github/workflows/openapi-types.yml` boots `pnpm --filter @iguanatrader/web dev` and runs `lhci autorun` against `http://localhost:5173/login`. Baselines are stored in `.lighthouseci/` and uploaded as GHA artefacts.

**Alternatives considered**:
- **Run against `pnpm preview` (production build)**: more representative of prod perf, but requires the auth flow to work end-to-end (FastAPI backend + seeded tenant) — too heavy for a smoke. Slice W1 may switch this to preview when the dashboard surface is non-trivial.
- **Run against the deployed staging URL**: no staging deployment yet (Wave 0 is foundation, no live env).

**Rationale**: dev-mode Lighthouse catches accessibility regressions (a11y is dev-mode invariant) and bundle-size warnings. Perf scores will be artificially low (no minification) — the workflow uses Lighthouse's `assertions` config to only fail on a11y < 90, NOT on perf < 90.

### D8. `cli/main.py` Typer app is empty in slice 5 — but the auto-discovery loop is wired

**Decision**: `apps/api/src/iguanatrader/cli/main.py` constructs `app = typer.Typer()`, calls `_discover_and_register_subcommands(app)` which `iter_modules`-loads each module under `iguanatrader.cli` (excluding `main` itself), imports it, and `app.add_typer(module.app, name=module.__name__)` for each that exports a top-level `app: typer.Typer`. Slice 5 ships zero subcommands; slice T4's `bootstrap_tenant.py` (or similar) is the first concrete addition.

**Rationale**: same anti-collision logic as routes / SSE. Slice T4 adds a file, not an edit.

### D9. RFC 7807 type URIs canonicalised to `urn:iguanatrader:error:<kebab-name>` — slice 4 D6 deviation rectified post-hoc

**Decision**: every `IguanaError` subclass's `type_uri` follows the `urn:iguanatrader:error:<kebab-name>` convention (already true in `iguanatrader.shared.errors`). Slice 4's `routes/auth.py::login` returned the zero-tenant 503 with `type="https://iguanatrader.local/problems/not-bootstrapped"` (URL form) — a one-off deviation. Slice 5 cleans this up by introducing `BootstrapNotReadyError(IguanaError)` with `type_uri="urn:iguanatrader:error:not-bootstrapped"` and updates `routes/auth.py` to `raise BootstrapNotReadyError(...)`. The handler renders the canonical urn form.

**Alternatives considered**:
- **Keep the URL form**: clients can dereference the URL to a doc page (RFC 7807 mentions this as a valid pattern). But our type URIs don't actually resolve to anything — the docs live in `docs/gotchas.md` / runbook references, not at `iguanatrader.local/problems/...`. The urn form is more honest.

**Rationale**: consistency. Every error type renders with the same scheme; clients pattern-match on a known prefix.

### D10. Exception handler order matters: `IguanaError` first, `Exception` second

**Decision**: register handlers in this order: `app.add_exception_handler(IguanaError, _render_problem)` first, then `app.add_exception_handler(Exception, _render_internal)`. FastAPI matches exception handlers most-specific-first by MRO. `IguanaError` handler catches anything in the project's hierarchy; `Exception` handler catches everything else (third-party library errors, AssertionErrors leaking out of routes, etc.) and wraps as `InternalError` (status 500, type `urn:iguanatrader:error:internal`) before rendering.

**Rationale**: defence-in-depth. NFR-O8 requires every error path to emit a structured log; without the `Exception` fallback, a third-party library raising would skip the breadcrumb. With both, every path is covered.

## Risks / Trade-offs

- **[Risk] Dynamic import of `iguanatrader.api.routes.<x>` at app boot fails silently** → if a route module raises on import (broken syntax, missing dep), the route family is silently absent. **Mitigation**: the discovery loop catches `ImportError` + `Exception`, emits structlog `api.router.import_failed` with module name + exc info, and re-raises so the app fails to boot loudly. Tests assert that `create_app()` raises if a stub broken module is dropped under `routes/`.

- **[Risk] OpenAPI regeneration in CI commits churn** → every PR that touches a route / DTO triggers a bot commit on the branch. The diff is sometimes noisy (e.g., field ordering shifts). **Mitigation**: pin `openapi-typescript` major version in `package.json`; require deterministic field-order output (the tool supports this via flags); set `--no-additional-properties` to keep the generated type tight. The bot commit is by design — same pattern as `regenerate-lock.yml` already in the repo.

- **[Risk] Lighthouse CI failing on perf score (artificial low in dev mode)** → developers are tempted to add `--no-verify` or skip the step. **Mitigation**: the assertions config explicitly excludes perf score; only a11y < 90 fails the workflow. Performance baselines are tracked but informational. Slice W1 may add prod-build Lighthouse later when the dashboard surface justifies it.

- **[Risk] Typer CLI auto-discovery imports modules at boot, slowing CLI startup** → especially relevant if a subcommand has heavy imports (e.g., trading models loading numpy). **Mitigation**: subcommand modules SHOULD use lazy imports (`def my_command(): import numpy; ...` not module-level `import numpy`). Document the convention in `apps/api/cli/__init__.py` docstring + add to `docs/gotchas.md`.

- **[Risk] `Exception` fallback handler catches `HTTPException` from FastAPI itself, breaking 404 / 422 responses** → FastAPI's built-in error responses for missing routes / validation failures would route through our handler and render as `InternalError`. **Mitigation**: the `Exception` handler explicitly checks `isinstance(exc, (HTTPException, RequestValidationError))` and re-raises (FastAPI's default handlers take over). Only "true" unhandled exceptions get the 500 + Problem treatment.

- **[Trade-off] Buildless `packages/shared-types/`**: we don't ship a `dist/` so any external consumer (if we ever expose this package) needs TypeScript-aware tooling. For internal pnpm-workspace consumers (apps/web, future apps/admin), this is fine. Documented as a v2 SaaS revisit.

- **[Trade-off] D9 introduces a NEW `BootstrapNotReadyError` subclass** — slice 5 grows the `IguanaError` hierarchy by one. Out of "no IguanaError subclass additions" scope clause? Strictly yes; the scope clause was about avoiding gratuitous additions, this one is the rectification of a slice-4 inconsistency, not a new error semantically. Documented inline in `shared/errors.py` as "added 2026-05-05 by slice api-foundation-rfc7807 to canonicalise type URI scheme; semantically equivalent to slice 4's inline 503 Problem".

## Migration Plan

This slice has no live deployment to migrate from. Deployment path:

1. Merge slice 5 to main.
2. Bot commits regenerated `packages/shared-types/src/index.ts` on first push (CI workflow auto-fires).
3. Slice 4's `routes/auth.py` already-shipped `_problem_response` calls collapse to `raise IguanaError(...)`. Wire-format-identical, so user-agents see no change. Integration test `test_auth_flow.py` continues to assert the same RFC 7807 body shapes.
4. Slice W1+ imports `@iguanatrader/shared-types` as needed; nothing breaks until then.

Rollback = revert PR. The dynamic discovery is opt-in (modules without a `router` are silently skipped — slice 4's auth router stays registered manually if the dynamic loop is removed). No schema changes, no destructive operations.

## Open Questions

- **Q**: Should the `Problem` Pydantic model carry the `extras` extension fields per RFC 7807 §3.2 (additional context like `errors: list[ErrorDetail]`)? **Tentative answer**: yes, via Pydantic's `model_config = ConfigDict(extra="allow")`; slice 5 lands the base model + `errors: list[ErrorDetail] | None` field; concrete error subclasses populate it as needed (e.g., a `ValidationError` with field-level details). Documented in spec scenarios.

- **Q**: Lighthouse CI assertions threshold — a11y ≥ 90 hard / a11y ≥ 95 hard? **Tentative answer**: 90 for slice 5 (foundation pre-pattern; the surface is just `/login` which is mostly form fields). Slice W1 raises to 95 once the dashboard skeleton lands.

- **Q**: Does `cli/main.py` ship a `--version` flag in slice 5 even though there are no subcommands? **Tentative answer**: yes — Typer's `--version` callback is one line, and it gives operators a sanity check that `python -m iguanatrader.cli` actually runs even before T4 lands real commands. Reads from `pyproject.toml::version` via `importlib.metadata.version("iguanatrader")`.
