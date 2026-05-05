## 1. Backend setup

- [x] 1.1 Add auth-specific runtime deps to root `pyproject.toml`: `pyjwt[crypto]>=2.8`, `argon2-cffi>=23.1`, `slowapi>=0.1.9`.
- [x] 1.2 Add dev dep `httpx>=0.27` (FastAPI test client).
- [x] 1.3 Add module-level Argon2 parameter constants to `apps/api/src/iguanatrader/api/__init__.py` (new file): `ARGON2_TIME_COST=3`, `ARGON2_MEMORY_KIB=65536`, `ARGON2_PARALLELISM=4`, `ARGON2_HASH_LEN=32`, `ARGON2_SALT_LEN=16`. Each is overridable via env var (`IGUANATRADER_ARGON2_*`).
- [x] 1.4 Add **FastAPI foundation runtime deps** to root `pyproject.toml` (slice 4 ships these as a **pre-pattern**; slice 5 `api-foundation-rfc7807` later layers RFC 7807 exception handlers + dynamic-discovery + OpenAPI typegen on top, but does NOT remove): `fastapi>=0.115`, `pydantic>=2.9`, `pydantic[email]` extras, `email-validator>=2.0`, `structlog>=24.4`, `python-multipart>=0.0.9` (FastAPI form-data parsing), `uvicorn[standard]>=0.30` (dev / test ASGI runtime). Document in the slice 4 PR description as "FastAPI foundation pre-pattern; slice 5 follow-up filed."
- [x] 1.5 Create minimal FastAPI app factory at `apps/api/src/iguanatrader/api/app.py`: `def create_app() -> FastAPI` returning an app with the slowapi `Limiter` attached to `app.state.limiter` and the `auth_router` registered manually (`app.include_router(auth_router, prefix="/api/v1")`). Slice 5 will refactor router registration to dynamic discovery via `pkgutil.iter_modules`. Wire structlog config import at module top so test fixtures get JSON logs out of the box. Add a `__main__.py` shim so `python -m iguanatrader.api` boots uvicorn for ad-hoc smoke testing (used by 7.6 manual smoke).
- [x] 1.6 Lock root `poetry.lock` via the `.github/workflows/regenerate-lock.yml` workflow_dispatch trigger (per gotcha #18 local poetry is broken). Pull the regenerated lock back to the branch before continuing to group 2.

## 2. Backend — auth primitives

- [x] 2.1 Create `apps/api/src/iguanatrader/api/auth.py` with: `hash_password(plain: str) -> str` (Argon2id), `verify_password(plain: str, hashed: str) -> bool` (returns False on mismatch, NEVER raises), `encode_jwt(payload: dict, exp_seconds: int) -> str`, `decode_jwt(token: str) -> dict | None` (returns None on expired or invalid; structlog event emitted), `should_rotate(exp_unix: int, now_unix: int) -> bool` (True if `exp - now < 1800`).
- [x] 2.2 Add a `Role` enum in `apps/api/src/iguanatrader/api/auth.py`: `Role.tenant_user`, `Role.god_admin`. Migration `0002_users_role_enum.py` renames CHECK from slice-3 legacy `('admin','user')` to `('tenant_user','god_admin')`; uses Alembic `batch_alter_table` per slice-3 D6 SQLite pattern.
- [x] 2.3 Create `apps/api/src/iguanatrader/api/deps.py` with FastAPI dependency `get_current_user(request, response, session)`: read cookie → decode JWT → check 7-day cookie ceiling via `login_at` claim → load User from DB (tenant_id_var UNSET — bootstrap) → set tenant_id_var → bind structlog contextvars (tenant_id, user_id, correlation_id) → if rotation due, attach Set-Cookie → return User. Single Python contextvar (tenant_id_var) drives SQL listener; structlog auto-binding handles user_id/correlation_id.
- [x] 2.4 Add the `requires_role(*roles: Role)` factory in `deps.py`: returns a Depends callable that checks `user.role_enum in roles`; raises `HTTPException(403)` on mismatch with the `auth.role.mismatch` structlog event.
- [x] 2.5 Hand-write unit tests `apps/api/tests/unit/test_auth_primitives.py` covering: `hash_password` round-trip + wrong-input + invalid-hash defensive returns False; `encode_jwt`/`decode_jwt` round-trip; expired/tampered/garbage token returns None; `should_rotate` strict less-than boundary cases; Role enum value parity with migration 0002 CHECK; `hash_email_for_log` 16-hex-char digest determinism.

## 3. Backend — auth routes

- [x] 3.1 Create `apps/api/src/iguanatrader/api/dtos/auth.py` with Pydantic v2 models: `LoginRequest(email: EmailStr, password: SecretStr)`, `LoginResponse(redirect_to: str)`, `MeResponse(user_id: UUID, tenant_id: UUID, email: EmailStr, role: Role, created_at: datetime)`. Configure `SecretStr` to never serialise.
- [x] 3.2 Create `apps/api/src/iguanatrader/api/routes/auth.py` with `APIRouter(prefix="/auth")` exposing: `POST /login`, `POST /logout`, `GET /me`. Wire each route to its dependency (Login is open; Logout is open / idempotent; `/me` uses `get_current_user`).
- [x] 3.3 In `routes/auth.py`'s `POST /login`: detect zero-tenant bootstrap state (count `Tenant` rows; if 0 → 503 with RFC 7807 Problem Detail per spec scenario "First-tenant bootstrap not yet performed").
- [x] 3.4 In `routes/auth.py`'s `POST /login`: for failed login (wrong password OR email-not-found), run an Argon2id verify against a fixed dummy hash to keep timing constant. Return 401 with uniform Problem Detail; emit `auth.login.failure` with `email_hash` (NOT email).
- [x] 3.5 In `routes/auth.py`'s `POST /login`: on success, encode JWT with claims `{sub: user_id, tenant_id, role, login_at: <now>}` (24h exp); compute cookie Max-Age from `login_at + 7d - now`; emit `auth.login.success`.
- [x] 3.6 Wire slowapi rate-limiter in `apps/api/src/iguanatrader/api/app.py`: `Limiter(key_func=lambda r: f"{get_remote_address(r)}:{r.json().get('email', '')}", default_limits=["5/minute"])`. Decorate the login endpoint with `@limiter.limit("5/minute")`. Custom 429 handler returns RFC 7807 with `Retry-After` header.
- [x] 3.7 Register the auth router in `app.py` (`app.include_router(auth_router, prefix="/api/v1")`). NOTE: slice 5 (`api-foundation-rfc7807`) will refactor this to dynamic discovery — flag in PR description as known follow-up.

## 4. Backend — integration + property tests

- [x] 4.1 Create `apps/api/tests/integration/test_auth_flow.py`: pytest-asyncio fixture `seeded_tenant_user` that inserts a Tenant + User (Argon2id hash of known plaintext). Tests: login success → cookie set → /me → logout → /me 401. Asserts cookie flags (`HttpOnly`, `Secure`, `SameSite=Strict`, `Max-Age=604800`). Asserts cookie domain unset.
- [x] 4.2 Add `test_auth_flow.py::test_login_wrong_password_returns_401_uniform_with_not_found` (timing parity probe — soft assertion that durations are within 50ms tolerance).
- [x] 4.3 Add `test_auth_flow.py::test_login_rate_limited_after_5_attempts`: hammer 6 calls within 60s; assert 6th returns 429 with `Retry-After`. Use `slowapi`'s in-memory store (no Redis dep for MVP).
- [x] 4.4 Add `test_auth_flow.py::test_zero_tenant_bootstrap_returns_503`: drop all Tenant rows, call `/login`, assert 503 + Problem Detail body shape.
- [x] 4.5 Add `test_auth_flow.py::test_jwt_rotation_attaches_set_cookie_on_near_expiry_request`: encode a JWT with `exp = now + 25min`; call `/me` with that cookie; assert response has `Set-Cookie` header with a fresh JWT (decoded, has fresh `exp`).
- [x] 4.6 Add `test_auth_flow.py::test_7day_ceiling_returns_401_even_with_valid_jwt`: encode JWT whose `login_at` claim is 7d 1min ago; assert 401.
- [x] 4.7 Add `test_auth_flow.py::test_role_gating`: create a `tenant_user` and a `god_admin`; create a stub route guarded by `requires_role(Role.god_admin)`; tenant_user gets 403; god_admin gets 200.
- [x] 4.8 Create `apps/api/tests/property/test_jwt_round_trip.py` with Hypothesis: `@given(st.uuids(), st.uuids(), st.sampled_from(Role))` → encode → decode → assert payload preserved. 100 examples.

## 5. Frontend — login surface

- [x] 5.1 Create `apps/web/src/routes/(auth)/login/+page.svelte`: form with email Input + password Input + submit Button + footer + login-help card; renders inline `<style>` block with the locked OKLCH tokens (W1 will plant `tokens.css` later — until then, inline). Tracks the rate-limit countdown via `setInterval` when `form?.retry_after` is present.
- [x] 5.2 Create `apps/web/src/routes/(auth)/login/+page.server.ts` with form action: validate `redirect_to` against the allow-list (single leading `/`, no `//`, no `://`, no `\`); proxy POST to FastAPI `/api/v1/auth/login`; on 200 → propagate `Set-Cookie` to the response, return `redirect(302, redirect_to)`; on 401 → return `fail(401, { message: "Invalid credentials" })`; on 429 → return `fail(429, { message: "...", retry_after: <seconds> })`; on 503 → return `fail(503, { message: "Not bootstrapped", detail: "..." })`.
- [x] 5.3 Create `apps/web/src/hooks.server.ts`: on every request to a path matching the `(app)` route group, fetch `/api/v1/auth/me`; if 401 → 302 to `/login?redirect_to=<encoded path+search>`. Stash the user in `event.locals.user` for downstream loaders.
- [x] 5.4 Add a Playwright e2e (or SvelteKit's built-in `vitest` + `@testing-library/svelte` if Playwright is too heavy at MVP) covering: cold visit to `/portfolio` → 302 to `/login?redirect_to=%2Fportfolio` → submit form with valid credentials → land on `/portfolio` (stub page).

## 6. Documentation + gotchas

- [x] 6.1 Append to `docs/gotchas.md`: gotcha #24 — Argon2id parameter rationale (D4); gotcha #25 — cookie Secure flag dev override (`IGUANATRADER_DEV_INSECURE_COOKIE=1`); gotcha #26 — JWT secret rotation procedure (link to runbook); gotcha #27 — SameSite=Strict blocks cross-site deep links (acceptable internal-tool trade-off); gotcha #28 — `get_current_user` ContextVar bootstrap-vs-isolated boundary (D7).
- [x] 6.2 Create `docs/runbooks/auth-secret-rotation.md`: step-by-step "rotate IGUANATRADER_JWT_SECRET" procedure (gen new 32-byte secret, update SOPS-encrypted env, restart API, expect all sessions to invalidate, expect users to redirect to `/login`).
- [x] 6.3 Update `apps/api/README.md` (or create) with the "first-run bootstrap" steps: install + `iguanatrader admin bootstrap-tenant` (TBD until slice T4 lands the CLI; for MVP, document the pytest fixture path + a SQL snippet operators can run manually).

## 7. Pre-merge verification

- [ ] 7.1 `mypy --strict apps/api/src/iguanatrader/api/` clean.
- [ ] 7.2 `pytest apps/api/tests/unit/test_auth_primitives.py apps/api/tests/integration/test_auth_flow.py apps/api/tests/property/test_jwt_round_trip.py` all green.
- [ ] 7.3 Coverage on `apps/api/src/iguanatrader/api/{auth,deps,routes/auth,dtos/auth}.py` ≥ 80% (NFR-M1).
- [ ] 7.4 `pre-commit run --from-ref origin/main --to-ref HEAD` passes (gitleaks + ruff + black + mypy strict + check-toml + block_manual_spec_edit).
- [ ] 7.5 Frontend lint: `pnpm --filter web check` (svelte-check + tsc) clean.
- [ ] 7.6 Manual smoke on localhost: bootstrap a tenant via test fixture, navigate to `/portfolio` → redirect to `/login` → log in → land on `/portfolio` (stub).
- [ ] 7.7 PR description includes "AI-reviewer signoff" subsection per release-management.md §4.5 (left blank initially; populated after CodeRabbit review).
