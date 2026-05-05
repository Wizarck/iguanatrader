## 1. Backend setup

- [ ] 1.1 Add runtime deps to `apps/api/pyproject.toml`: `pyjwt[crypto]>=2.8`, `argon2-cffi>=23.1`, `slowapi>=0.1.9`. Lock via the `regenerate-lock.yml` workflow.
- [ ] 1.2 Add dev dep `httpx>=0.27` (FastAPI test client) if not already present from slice 3.
- [ ] 1.3 Add module-level Argon2 parameter constants to a new file `apps/api/src/iguanatrader/api/__init__.py` (or reuse existing scaffolding from slice 3): `ARGON2_TIME_COST=3`, `ARGON2_MEMORY_KIB=65536`, `ARGON2_PARALLELISM=4`, `ARGON2_HASH_LEN=32`, `ARGON2_SALT_LEN=16`. Each is overridable via env var (`IGUANATRADER_ARGON2_*`).

## 2. Backend — auth primitives

- [ ] 2.1 Create `apps/api/src/iguanatrader/api/auth.py` with: `hash_password(plain: str) -> str` (Argon2id), `verify_password(plain: str, hashed: str) -> bool` (returns False on mismatch, NEVER raises), `encode_jwt(payload: dict, exp_seconds: int) -> str`, `decode_jwt(token: str) -> dict | None` (returns None on expired or invalid; structlog event emitted), `should_rotate(exp_unix: int, now_unix: int) -> bool` (True if `exp - now < 1800`).
- [ ] 2.2 Add a `Role` enum in `apps/api/src/iguanatrader/api/auth.py`: `Role.tenant_user`, `Role.god_admin`. Wire to the `users.role` column (slice 3 schema; if missing as enum, this slice adds an Alembic migration `0002_users_role_enum.py` to enforce CHECK constraint on `users.role`).
- [ ] 2.3 Create `apps/api/src/iguanatrader/api/deps.py` with FastAPI dependency `get_current_user(request: Request) -> User`: read cookie → decode JWT → load User + Tenant from DB (with `tenant_id_ctx` UNSET — bootstrap path) → set `tenant_id_ctx`, `user_id_ctx`, `correlation_id_ctx` ContextVars → if rotation due, attach `Set-Cookie` header to the response → return User.
- [ ] 2.4 Add the `requires_role(*roles: Role)` factory in `deps.py`: returns a Depends callable that checks `user.role in roles`; raises `HTTPException(403)` on mismatch with the `auth.role.mismatch` structlog event.
- [ ] 2.5 Hand-write a unit test `apps/api/tests/unit/test_auth_primitives.py` covering: `hash_password` round-trip with `verify_password`, `verify_password` with wrong input returns False (not raise), `encode_jwt` + `decode_jwt` round-trip, `decode_jwt` of expired token returns None, `decode_jwt` of tampered signature returns None, `should_rotate` boundary cases (exactly 1800s out, 1799s out, 1801s out).

## 3. Backend — auth routes

- [ ] 3.1 Create `apps/api/src/iguanatrader/api/dtos/auth.py` with Pydantic v2 models: `LoginRequest(email: EmailStr, password: SecretStr)`, `LoginResponse(redirect_to: str)`, `MeResponse(user_id: UUID, tenant_id: UUID, email: EmailStr, role: Role, created_at: datetime)`. Configure `SecretStr` to never serialise.
- [ ] 3.2 Create `apps/api/src/iguanatrader/api/routes/auth.py` with `APIRouter(prefix="/auth")` exposing: `POST /login`, `POST /logout`, `GET /me`. Wire each route to its dependency (Login is open; Logout is open / idempotent; `/me` uses `get_current_user`).
- [ ] 3.3 In `routes/auth.py`'s `POST /login`: detect zero-tenant bootstrap state (count `Tenant` rows; if 0 → 503 with RFC 7807 Problem Detail per spec scenario "First-tenant bootstrap not yet performed").
- [ ] 3.4 In `routes/auth.py`'s `POST /login`: for failed login (wrong password OR email-not-found), run an Argon2id verify against a fixed dummy hash to keep timing constant. Return 401 with uniform Problem Detail; emit `auth.login.failure` with `email_hash` (NOT email).
- [ ] 3.5 In `routes/auth.py`'s `POST /login`: on success, encode JWT with claims `{sub: user_id, tenant_id, role, login_at: <now>}` (24h exp); compute cookie Max-Age from `login_at + 7d - now`; emit `auth.login.success`.
- [ ] 3.6 Wire slowapi rate-limiter in `apps/api/src/iguanatrader/api/app.py`: `Limiter(key_func=lambda r: f"{get_remote_address(r)}:{r.json().get('email', '')}", default_limits=["5/minute"])`. Decorate the login endpoint with `@limiter.limit("5/minute")`. Custom 429 handler returns RFC 7807 with `Retry-After` header.
- [ ] 3.7 Register the auth router in `app.py` (`app.include_router(auth_router, prefix="/api/v1")`). NOTE: slice 5 (`api-foundation-rfc7807`) will refactor this to dynamic discovery — flag in PR description as known follow-up.

## 4. Backend — integration + property tests

- [ ] 4.1 Create `apps/api/tests/integration/test_auth_flow.py`: pytest-asyncio fixture `seeded_tenant_user` that inserts a Tenant + User (Argon2id hash of known plaintext). Tests: login success → cookie set → /me → logout → /me 401. Asserts cookie flags (`HttpOnly`, `Secure`, `SameSite=Strict`, `Max-Age=604800`). Asserts cookie domain unset.
- [ ] 4.2 Add `test_auth_flow.py::test_login_wrong_password_returns_401_uniform_with_not_found` (timing parity probe — soft assertion that durations are within 50ms tolerance).
- [ ] 4.3 Add `test_auth_flow.py::test_login_rate_limited_after_5_attempts`: hammer 6 calls within 60s; assert 6th returns 429 with `Retry-After`. Use `slowapi`'s in-memory store (no Redis dep for MVP).
- [ ] 4.4 Add `test_auth_flow.py::test_zero_tenant_bootstrap_returns_503`: drop all Tenant rows, call `/login`, assert 503 + Problem Detail body shape.
- [ ] 4.5 Add `test_auth_flow.py::test_jwt_rotation_attaches_set_cookie_on_near_expiry_request`: encode a JWT with `exp = now + 25min`; call `/me` with that cookie; assert response has `Set-Cookie` header with a fresh JWT (decoded, has fresh `exp`).
- [ ] 4.6 Add `test_auth_flow.py::test_7day_ceiling_returns_401_even_with_valid_jwt`: encode JWT whose `login_at` claim is 7d 1min ago; assert 401.
- [ ] 4.7 Add `test_auth_flow.py::test_role_gating`: create a `tenant_user` and a `god_admin`; create a stub route guarded by `requires_role(Role.god_admin)`; tenant_user gets 403; god_admin gets 200.
- [ ] 4.8 Create `apps/api/tests/property/test_jwt_round_trip.py` with Hypothesis: `@given(st.uuids(), st.uuids(), st.sampled_from(Role))` → encode → decode → assert payload preserved. 100 examples.

## 5. Frontend — login surface

- [ ] 5.1 Create `apps/web/src/routes/(auth)/login/+page.svelte`: form with email Input + password Input + submit Button + footer + login-help card; renders inline `<style>` block with the locked OKLCH tokens (W1 will plant `tokens.css` later — until then, inline). Tracks the rate-limit countdown via `setInterval` when `form?.retry_after` is present.
- [ ] 5.2 Create `apps/web/src/routes/(auth)/login/+page.server.ts` with form action: validate `redirect_to` against the allow-list (single leading `/`, no `//`, no `://`, no `\`); proxy POST to FastAPI `/api/v1/auth/login`; on 200 → propagate `Set-Cookie` to the response, return `redirect(302, redirect_to)`; on 401 → return `fail(401, { message: "Invalid credentials" })`; on 429 → return `fail(429, { message: "...", retry_after: <seconds> })`; on 503 → return `fail(503, { message: "Not bootstrapped", detail: "..." })`.
- [ ] 5.3 Create `apps/web/src/hooks.server.ts`: on every request to a path matching the `(app)` route group, fetch `/api/v1/auth/me`; if 401 → 302 to `/login?redirect_to=<encoded path+search>`. Stash the user in `event.locals.user` for downstream loaders.
- [ ] 5.4 Add a Playwright e2e (or SvelteKit's built-in `vitest` + `@testing-library/svelte` if Playwright is too heavy at MVP) covering: cold visit to `/portfolio` → 302 to `/login?redirect_to=%2Fportfolio` → submit form with valid credentials → land on `/portfolio` (stub page).

## 6. Documentation + gotchas

- [ ] 6.1 Append to `docs/gotchas.md`: gotcha #24 — Argon2id parameter rationale (D4); gotcha #25 — cookie Secure flag dev override (`IGUANATRADER_DEV_INSECURE_COOKIE=1`); gotcha #26 — JWT secret rotation procedure (link to runbook); gotcha #27 — SameSite=Strict blocks cross-site deep links (acceptable internal-tool trade-off); gotcha #28 — `get_current_user` ContextVar bootstrap-vs-isolated boundary (D7).
- [ ] 6.2 Create `docs/runbooks/auth-secret-rotation.md`: step-by-step "rotate IGUANATRADER_JWT_SECRET" procedure (gen new 32-byte secret, update SOPS-encrypted env, restart API, expect all sessions to invalidate, expect users to redirect to `/login`).
- [ ] 6.3 Update `apps/api/README.md` (or create) with the "first-run bootstrap" steps: install + `iguanatrader admin bootstrap-tenant` (TBD until slice T4 lands the CLI; for MVP, document the pytest fixture path + a SQL snippet operators can run manually).

## 7. Pre-merge verification

- [ ] 7.1 `mypy --strict apps/api/src/iguanatrader/api/` clean.
- [ ] 7.2 `pytest apps/api/tests/unit/test_auth_primitives.py apps/api/tests/integration/test_auth_flow.py apps/api/tests/property/test_jwt_round_trip.py` all green.
- [ ] 7.3 Coverage on `apps/api/src/iguanatrader/api/{auth,deps,routes/auth,dtos/auth}.py` ≥ 80% (NFR-M1).
- [ ] 7.4 `pre-commit run --from-ref origin/main --to-ref HEAD` passes (gitleaks + ruff + black + mypy strict + check-toml + block_manual_spec_edit).
- [ ] 7.5 Frontend lint: `pnpm --filter web check` (svelte-check + tsc) clean.
- [ ] 7.6 Manual smoke on localhost: bootstrap a tenant via test fixture, navigate to `/portfolio` → redirect to `/login` → log in → land on `/portfolio` (stub).
- [ ] 7.7 PR description includes "AI-reviewer signoff" subsection per release-management.md §4.5 (left blank initially; populated after CodeRabbit review).
