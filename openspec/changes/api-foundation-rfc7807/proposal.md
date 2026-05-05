## Why

Slice 4 (`auth-jwt-cookie`) shipped a working FastAPI app — but the wiring is provisional: the auth router is `app.include_router`-d manually in `app.py`, every error path returns RFC 7807 by hand-built `JSONResponse`, and the SvelteKit frontend has no typed client. Without a foundation contract, every subsequent slice (R5 research, T4 trading, K1 risk, P1 approval, etc.) duplicates the wiring boilerplate AND races on `app.py` edits — Wave 1+ parallel-safe execution depends on slices NOT touching the same file. This change plants the **anti-collision foundation pattern**: dynamic router/SSE/CLI discovery via `pkgutil.iter_modules`, a single global `IguanaError → RFC 7807` exception handler, and the `openapi-typescript` typegen pipeline that gives the SvelteKit layer a generated client. Now is the right time because slice 4 just merged with the manual `include_router` flagged as a known follow-up — slice 5 is the first opportunity to refactor before adding a second router family.

## What Changes

- **Dynamic router discovery** — replace `app.include_router(auth_router, prefix="/api/v1")` in `apps/api/src/iguanatrader/api/app.py` with a `pkgutil.iter_modules`-driven loop over `iguanatrader.api.routes` that loads every module's exported `router: APIRouter`. Slice 4's auth router stays unchanged; future slices add `routes/<name>.py` + nobody edits `app.py`.
- **Dynamic SSE discovery** — same pattern under `apps/api/src/iguanatrader/api/sse/__init__.py` so SSE endpoints (research streams, trading event feeds, approval channel) plug in without `app.py` churn.
- **Dynamic CLI subcommand discovery** — `apps/api/src/iguanatrader/cli/main.py` builds a Typer app that auto-discovers subcommand modules under `cli/`. Slice T4 lands the first real subcommand (`bootstrap-tenant`) without editing `cli/main.py`.
- **Global RFC 7807 exception handler** — `apps/api/src/iguanatrader/api/errors.py` registers `@app.exception_handler(IguanaError)` that calls `IguanaError.to_problem_dict()` and returns a `JSONResponse` with `media_type="application/problem+json"`. Routes raise `IguanaError` subclasses; the handler renders. Slice 4's `routes/auth.py::_problem_response` helper collapses to plain `raise AuthError(...)` / `raise ValidationError(...)`.
- **Common DTOs** — `apps/api/src/iguanatrader/api/dtos/common.py` exposes `Problem` (Pydantic v2 model matching RFC 7807) + `ErrorDetail` for nested error contexts (e.g., field-level validation failures).
- **OpenAPI typegen pipeline** — pre-existing `.github/workflows/openapi-types.yml` is wired to actually run: it boots the FastAPI app in CI, dumps `/openapi.json`, runs `openapi-typescript` to regenerate `packages/shared-types/src/index.ts`, and commits the diff. SvelteKit imports `@iguanatrader/shared-types` instead of hand-rolling DTO interfaces.
- **`packages/shared-types/` package boots** — slice 1 declared the workspace folder but left it empty (per the slice-1 archive); this slice plants `package.json` + `tsconfig.json` + a placeholder `src/index.ts` that the typegen pipeline overwrites on first CI run.
- **Lighthouse CI step** — added to the `openapi-types.yml` workflow per the original slice contract; runs Lighthouse against the SvelteKit dev server (`pnpm dev`) and surfaces accessibility / performance baselines.
- **No new routes** — every concrete route family (research, trading, risk, approval) lands in its own slice. Slice 5 is foundation-only.

## Capabilities

### New Capabilities

- `api-foundation`: RFC 7807 Problem Details contract for every error response; dynamic discovery patterns for routes / SSE endpoints / CLI subcommands; OpenAPI → TypeScript typegen pipeline. The anti-collision foundation that lets Waves 1-4 run parallel without touching shared `app.py` / `cli/main.py`.

### Modified Capabilities

(none — slice 4's `web-authentication` spec doesn't change at the requirement level; only the implementation of `routes/auth.py::_problem_response` collapses into the global handler.)

## Impact

- **Affected code (slice-5-owned, write-allowed)**:
  - `apps/api/src/iguanatrader/api/app.py` — refactor `app.include_router` block to dynamic `pkgutil.iter_modules` loop; register `IguanaError` exception handler; mount SSE discovery side-by-side.
  - `apps/api/src/iguanatrader/api/errors.py` (NEW) — exception handler + `Problem` rendering.
  - `apps/api/src/iguanatrader/api/dtos/common.py` (NEW) — `Problem`, `ErrorDetail`.
  - `apps/api/src/iguanatrader/api/sse/__init__.py` (NEW) — discovery loop scaffold.
  - `apps/api/src/iguanatrader/cli/__init__.py` + `cli/main.py` (NEW) — Typer app + auto-discovery.
  - `packages/shared-types/{package.json, tsconfig.json, src/index.ts}` (NEW) — TypeScript package.
  - `.github/workflows/openapi-types.yml` (MOD) — wire actual typegen step + Lighthouse CI step.
  - `apps/api/src/iguanatrader/api/routes/auth.py` (MOD) — collapse `_problem_response` calls into `raise AuthError(...)` / `raise ValidationError(...)` so the global handler renders.
- **Affected code (slice-3/4-owned, read-only consumed)**:
  - `iguanatrader.shared.errors.IguanaError` hierarchy + `to_problem_dict()` method (slice 2 contract; consumed unchanged).
- **Affected APIs**: every endpoint's error contract becomes uniform RFC 7807 (was ad-hoc `JSONResponse` in slice 4 — same wire format, just centralized). Auth endpoints' behaviour is unchanged from the user-agent perspective.
- **Affected dependencies**:
  - `typer>=0.12,<1.0` — runtime dep for the CLI scaffold.
  - `openapi-typescript@^7` — already in root `package.json`; this slice wires it.
  - `@lhci/cli@^0.14` — devDep added to root `package.json` for Lighthouse CI step.
- **Prerequisites**: `persistence-tenant-enforcement` (slice 3) — provides the SQLAlchemy listener that the dynamic-discovery routes will rely on once they query tenant-scoped tables.
- **Capability coverage** (per `docs/openspec-slice.md` row 5): foundation-only; targets NFR-P7 (latency budget — RFC 7807 handler MUST add <1ms p99 to error paths) + NFR-O8 (observability — every error renders a structlog `<context>.<error_type>.unhandled` event with the IguanaError's `type` URI).
- **Out of scope** (per `docs/openspec-slice.md` row 5 and bridge contract):
  - Concrete route families (research / trading / risk / approval / observability) — each slice owns its `routes/<name>.py`.
  - SvelteKit consumption of `@iguanatrader/shared-types` — slice W1 (`dashboard-svelte-skeleton`) does the actual import + replacement of inline TS types.
  - The `bootstrap-tenant` CLI subcommand (slice T4); slice 5 just lands the empty Typer app + discovery scaffold.
  - GraphQL or any non-REST API surface (out of MVP).
