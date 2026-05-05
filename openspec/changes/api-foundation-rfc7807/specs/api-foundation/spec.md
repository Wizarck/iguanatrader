## ADDED Requirements

### Requirement: All `IguanaError` exceptions render as RFC 7807 Problem Details

The system SHALL register a global FastAPI exception handler that intercepts every `iguanatrader.shared.errors.IguanaError` (and subclasses) raised inside a route, calls `to_problem_dict()` on the exception, and returns a `JSONResponse` with `media_type="application/problem+json"` and the corresponding HTTP status code from the exception's `default_status` attribute.

#### Scenario: Route raises AuthError

- **WHEN** a route raises `AuthError("Not authenticated")` (e.g., during `get_current_user` dep evaluation)
- **THEN** the response is `401 Unauthorized` with `Content-Type: application/problem+json`
- **AND** the body is `{"type": "urn:iguanatrader:error:auth", "title": "Authentication Required", "status": 401, "detail": "Not authenticated"}`
- **AND** no other exception handler intercepts (the `IguanaError` handler matches first per FastAPI MRO ordering)

#### Scenario: Route raises a custom IguanaError subclass

- **WHEN** a route raises `BootstrapNotReadyError(detail="Run iguanatrader admin bootstrap-tenant <slug>")`
- **THEN** the response is `503 Service Unavailable` with the canonical `urn:iguanatrader:error:not-bootstrapped` type URI
- **AND** the body's `detail` field carries the operator-facing CLI hint
- **AND** the structlog event `auth.login.bootstrap_required` is emitted (route handler emits before raising)

#### Scenario: Multiple errors in one request lifecycle

- **WHEN** a route's dependency chain raises `ValidationError`, then a downstream catch-block re-raises as `InternalError`
- **THEN** only the outer (final) exception is rendered to the response
- **AND** the original `ValidationError` is logged at WARN level via the structlog event chain

### Requirement: Unhandled exceptions render as InternalError + emit structured log breadcrumb

The system SHALL register a fallback exception handler for `Exception` that wraps any non-`IguanaError` (and non-FastAPI-builtin) exception as `InternalError` and renders it as RFC 7807 Problem Detail with HTTP 500. The handler SHALL emit a structlog event `api.unhandled_exception` with `exc_info=True` so the underlying exception is captured in observability stores.

#### Scenario: Third-party library raises ValueError

- **WHEN** a route calls `int("not-a-number")` which raises `ValueError`
- **THEN** the response is `500 Internal Server Error` with body `{"type": "urn:iguanatrader:error:internal", "title": "Internal Error", "status": 500, ...}`
- **AND** the structlog event `api.unhandled_exception` is emitted with `exc_info` showing the original ValueError + stack trace
- **AND** the response body's `detail` is a generic message ("Unexpected server error") — NOT the raw ValueError text (no PII / internal paths leaked to the client)

#### Scenario: FastAPI's own HTTPException passes through

- **WHEN** a route raises `fastapi.HTTPException(status_code=422, detail=[{...}])` (e.g., Pydantic validation failure auto-converted by FastAPI)
- **THEN** FastAPI's default handler renders the response (the `Exception` fallback re-raises HTTPException + RequestValidationError)
- **AND** the response body is FastAPI's native `{"detail": [...]}` format, NOT the Problem Details format
- **AND** the structlog event `api.unhandled_exception` is NOT emitted (this isn't an unexpected exception — it's user input validation)

### Requirement: Routes are discovered dynamically via `pkgutil.iter_modules`

The system SHALL discover route modules at app boot by iterating `pkgutil.iter_modules(iguanatrader.api.routes.__path__)`, importing each module, and registering its top-level `router: APIRouter` attribute via `app.include_router(module.router, prefix="/api/v1")`. Modules that do not export a `router` attribute SHALL be skipped with a structlog warning event `api.router.skipped`.

#### Scenario: New route module added under api/routes/

- **WHEN** a developer drops `apps/api/src/iguanatrader/api/routes/research.py` exporting `router: APIRouter`
- **AND** the FastAPI app is restarted
- **THEN** the new router is registered at `/api/v1` without any edit to `app.py` or `routes/__init__.py`
- **AND** the structlog event `api.router.registered` is emitted with `module="iguanatrader.api.routes.research"`

#### Scenario: Module without router is skipped

- **WHEN** a module under `api/routes/` does not export a `router` attribute (e.g., a helper module)
- **THEN** the discovery loop skips it
- **AND** emits structlog `api.router.skipped` with `module=<name>` and `reason="no_router_attribute"`

#### Scenario: Module raises on import

- **WHEN** a module under `api/routes/` raises `ImportError` or any `Exception` at import time
- **THEN** the discovery loop emits structlog `api.router.import_failed` with `module=<name>` and `exc_info=True`
- **AND** the original exception is re-raised so the FastAPI app fails to boot loudly (NOT a silent missing route family)

### Requirement: SSE endpoints are discovered dynamically via the same pattern as routes

The system SHALL provide `apps/api/src/iguanatrader/api/sse/__init__.py` whose `register_sse(app)` helper iterates `pkgutil.iter_modules(iguanatrader.api.sse.__path__)` and registers each module's `router: APIRouter` under prefix `/api/v1/stream`. SSE modules MAY expose `StreamingResponse`-yielding endpoints; FastAPI handles the underlying ASGI streaming.

#### Scenario: New SSE module added

- **WHEN** a developer drops `apps/api/src/iguanatrader/api/sse/research_stream.py` exporting `router: APIRouter` with a `GET /research/{symbol}/feed` endpoint
- **AND** the FastAPI app is restarted
- **THEN** the SSE endpoint is reachable at `/api/v1/stream/research/{symbol}/feed`
- **AND** no edit to `sse/__init__.py` is required

### Requirement: CLI subcommands are discovered dynamically via Typer auto-registration

The system SHALL provide `apps/api/src/iguanatrader/cli/main.py` whose top-level `app: typer.Typer` is built by iterating `pkgutil.iter_modules(iguanatrader.cli.__path__)`, importing each module (excluding `main` itself), and `add_typer`-ing each module's exported `app: typer.Typer` under the module's bare name. The CLI entrypoint SHALL be reachable as `python -m iguanatrader.cli` (and via the project's pyproject `[tool.poetry.scripts]` script alias once T4 wires it).

#### Scenario: CLI runs with no subcommands (slice 5 baseline)

- **WHEN** `python -m iguanatrader.cli --version` is invoked
- **THEN** the version string from `iguanatrader.__version__` is printed
- **AND** exit code is `0`

#### Scenario: New CLI subcommand added

- **WHEN** a developer drops `apps/api/src/iguanatrader/cli/bootstrap_tenant.py` exporting `app: typer.Typer` with a single command
- **AND** `python -m iguanatrader.cli --help` is invoked
- **THEN** the help output lists `bootstrap-tenant` as an available subcommand
- **AND** no edit to `cli/main.py` is required

### Requirement: OpenAPI schema regenerates `packages/shared-types/src/index.ts` in CI

The system SHALL provide a CI workflow (`.github/workflows/openapi-types.yml`) that, on every push to a `slice/**` or `feat/**` branch, boots the FastAPI app, fetches `/openapi.json`, runs `openapi-typescript` to regenerate `packages/shared-types/src/index.ts`, and commits the diff back to the branch as a workflow-bot commit when the regenerated file differs from the committed copy.

#### Scenario: Slice introduces a new DTO

- **WHEN** a slice adds a Pydantic model to a route's response_model and pushes the branch
- **THEN** the openapi-types workflow fires
- **AND** the regenerated `packages/shared-types/src/index.ts` includes the new TypeScript interface
- **AND** the workflow commits the diff with message `chore(types): regenerate shared-types from /openapi.json`
- **AND** the branch's next CI run picks up the typed client

#### Scenario: No DTO changes — workflow no-op

- **WHEN** a slice changes only internal helpers (no Pydantic model edits) and pushes
- **THEN** the openapi-types workflow runs but the regenerated file is byte-identical to HEAD
- **AND** no bot commit is created

### Requirement: `Problem` Pydantic model is the canonical RFC 7807 schema

The system SHALL expose `apps/api/src/iguanatrader/api/dtos/common.py::Problem` as a Pydantic v2 `BaseModel` with fields `type: str`, `title: str`, `status: int`, `detail: str | None = None`, `instance: str | None = None`, plus `errors: list[ErrorDetail] | None = None` for nested error context. The model SHALL be referenced by every error response's OpenAPI schema so the typegen pipeline emits a `Problem` TypeScript interface.

#### Scenario: 401 response declares Problem schema

- **WHEN** the OpenAPI schema for `POST /api/v1/auth/login` is generated
- **THEN** the `responses["401"]["content"]["application/problem+json"]["schema"]` references the `Problem` component
- **AND** the regenerated `packages/shared-types/src/index.ts` exports a `Problem` interface with the canonical fields

#### Scenario: ErrorDetail nests for field validation

- **WHEN** a `ValidationError` is raised with `errors=[ErrorDetail(field="email", code="invalid_format", detail="not an email")]`
- **THEN** the rendered Problem body's `errors` array is `[{"field": "email", "code": "invalid_format", "detail": "not an email"}]`

### Requirement: Lighthouse CI step asserts a11y ≥ 90 on the SvelteKit dev server

The system SHALL include a Lighthouse CI step in `.github/workflows/openapi-types.yml` (or a sibling workflow) that boots `pnpm --filter @iguanatrader/web dev`, runs `lhci autorun` against `http://localhost:5173/login`, and fails the workflow when the accessibility score is below 90. Performance + best-practices scores are tracked as informational baselines (no hard threshold).

#### Scenario: a11y regression on /login

- **WHEN** a slice introduces an `<input>` without an associated `<label>` on the login surface
- **AND** the workflow runs Lighthouse
- **THEN** the a11y score drops below 90
- **AND** the workflow fails with the specific Lighthouse audit ID

#### Scenario: perf score below 90 — workflow passes

- **WHEN** dev-mode rendering produces a perf score of 70 (no minification, source-map overhead)
- **THEN** the Lighthouse step passes (perf is informational only in slice 5 baseline; slice W1 may bump to a hard threshold once dashboard surface stabilises)

### Requirement: `BootstrapNotReadyError` replaces slice 4's inline 503 zero-tenant Problem

The system SHALL define `iguanatrader.shared.errors.BootstrapNotReadyError(IguanaError)` with `default_status=503` and `type_uri="urn:iguanatrader:error:not-bootstrapped"`. The slice 4 `apps/api/src/iguanatrader/api/routes/auth.py::login` zero-tenant guard (which previously returned a hand-built `JSONResponse` with `type="https://iguanatrader.local/problems/not-bootstrapped"`) SHALL be refactored to `raise BootstrapNotReadyError(detail=...)` so the global handler renders the canonical urn-form type URI.

#### Scenario: Zero-tenant login attempt

- **WHEN** `POST /api/v1/auth/login` arrives and the `tenants` table has zero rows
- **THEN** the route raises `BootstrapNotReadyError(detail="Run iguanatrader admin bootstrap-tenant <slug> ...")`
- **AND** the global handler renders `{"type": "urn:iguanatrader:error:not-bootstrapped", "title": "Service Not Bootstrapped", "status": 503, "detail": "Run iguanatrader admin bootstrap-tenant <slug> ..."}`
- **AND** the structlog event `auth.login.bootstrap_required` is emitted (matching the slice 4 contract — event name is unchanged)
