## Why

The dashboard, CLI ops, and approval channels all assume a `tenant_user` identity is resolved to a `tenant_id` ContextVar before any query runs (per `persistence-tenant-enforcement` slice 3). Until this slice lands, no UI surface can authenticate a request, no `/api/v1/*` endpoint can enforce `requires_role`, and slice W1 (`dashboard-svelte-skeleton`) cannot wire its `(app)` route guard. Slice 4 plants the JWT-cookie session contract that **every** post-Wave-0 slice depends on for identity propagation.

The UX contract for this surface was locked 2026-05-05 by Sally + Arturo (`docs/ux/j0.md`, `docs/ux/components.md` REFINED v1) and is canonical for slice 4 onward.

## What Changes

- **New** `apps/api/src/iguanatrader/api/auth.py`: JWT encode/decode with HS256 + 24h expiry + refresh rotation; `argon2-cffi` password hashing (Argon2id, sane defaults documented in `docs/gotchas.md`).
- **New** `apps/api/src/iguanatrader/api/deps.py`: FastAPI dependency `get_current_user` that reads cookie, decodes JWT, loads `User` + `Tenant` rows, sets `tenant_id` + `user_id` ContextVars, returns the loaded user. `requires_role(...)` factory for route gating (every operational mutating endpoint accepts `tenant_user`; platform endpoints accept `god_admin` only and are NOT exposed in the SvelteKit dashboard — see `docs/personas-jtbd.md` §RBAC Matrix).
- **New** `apps/api/src/iguanatrader/api/routes/auth.py`: `POST /api/v1/auth/login` (Argon2id verify + cookie set), `POST /api/v1/auth/logout` (cookie clear), `POST /api/v1/auth/refresh` (rotate JWT), `GET /api/v1/auth/me` (current user payload). All routes structlog-instrumented with `auth.<entity>.<action>` event names.
- **New** `apps/api/src/iguanatrader/api/dtos/auth.py`: Pydantic v2 models `LoginRequest`, `LoginResponse`, `MeResponse`. Email is `EmailStr`; password is `SecretStr`; never serialised in responses.
- **New** rate-limit configuration via `slowapi`: 5/min on `/auth/login` (NFR-S5 anti-brute-force). Configured at app factory level so other endpoints (`/research/refresh` later) reuse the limiter.
- **New** `apps/web/src/routes/(auth)/login/+page.svelte` + `+page.server.ts`: SvelteKit form action POSTs to `/api/v1/auth/login`; on 200 sets cookie + 302 to `redirect_to` (allow-listed same-origin paths only); on 422 rerenders with `Input` error state; on 429 rerenders with destructive `Alert` rate-limit banner counting down via `Retry-After` header. Uses locked Sally tokens (`docs/ux/DESIGN.md`) + Lucide icons (`docs/ux/components.md` §0.5).
- **New** `apps/web/src/hooks.server.ts`: SvelteKit server hook that reads the JWT cookie on every request to a `(app)` route group; on absent/expired/invalid cookie → 302 redirect to `/login?redirect_to=<current>`. Hands off the `+error.svelte` rendering to slice W1 (which owns the global error boundary).
- **New** `apps/api/tests/integration/test_auth_flow.py`: login → cookie set → `/me` → logout → `/me` returns 401. Plus rate-limit test (6th call within 60s returns 429), Argon2id verify-fail returns 401 (not 403), JWT-expired returns 401.
- **New** `apps/api/tests/property/test_jwt_round_trip.py`: Hypothesis property test — encode/decode round-trip preserves payload for any user/tenant combination.
- **First-tenant-as-admin contract**: when `tenants` table has 0 rows, the first `POST /api/v1/auth/login` with `tenants` table empty refuses with a 503 + helpful Problem Detail "iguanatrader admin bootstrap-tenant <slug>". The CLI command `iguanatrader admin bootstrap-tenant` lands in slice T4; until then, integration tests use a pytest fixture that seeds a tenant + user directly.

## Capabilities

### New Capabilities

- `web-authentication`: cookie-based JWT session contract — encode/decode/rotate, password hashing (Argon2id), login/logout/refresh/me HTTP routes, SvelteKit cookie hook + `(auth)/login` form action, rate-limit, redirect-to allow-listing, structlog event emission with `context="auth"`. Anchors the `requires_role` decorator that every later slice consumes for RBAC enforcement. Does NOT cover the dashboard skeleton, the `+error.svelte` boundary, the iconography install, or per-tenant brand customisation — those are owned by W1 and v2 SaaS respectively.

### Modified Capabilities

(none — this is a greenfield capability; no prior auth contract to delta.)

## Impact

**Affected code (write-allowed by this slice)**:
- `apps/api/src/iguanatrader/api/{auth,deps}.py` (new)
- `apps/api/src/iguanatrader/api/routes/auth.py` (new)
- `apps/api/src/iguanatrader/api/dtos/auth.py` (new)
- `apps/api/src/iguanatrader/api/app.py` (modified — register auth router + slowapi middleware; per the dynamic-discovery anti-collision pattern in slice 5 `api-foundation-rfc7807`, this slice is allowed to register the limiter at the app factory because slice 5 has not yet landed; once 5 lands, the auth router will be auto-discovered via `pkgutil.iter_modules` and the manual register can be dropped — flagged as a follow-up in slice 5)
- `apps/web/src/routes/(auth)/login/{+page.svelte,+page.server.ts}` (new)
- `apps/web/src/hooks.server.ts` (new — the cookie + redirect-to hook; W1 will extend this with the `+error.svelte` integration)
- `apps/api/tests/integration/test_auth_flow.py` (new)
- `apps/api/tests/property/test_jwt_round_trip.py` (new)
- `migrations/versions/0002_users_seed_constraints.py` (only if needed — slice 3 already provided `users` + `tenants` + `authorized_senders` schema; this slice adds CHECK constraints if missing, e.g. `users.password_hash` non-empty)
- `docs/gotchas.md` (append Argon2id parameter rationale + cookie-flag matrix)

**Read-only paths (consult, don't edit)**:
- `apps/api/src/iguanatrader/persistence/{session,tenant_listener,base}.py` (slice 3)
- `apps/api/src/iguanatrader/shared/{contextvars,errors,time}.py` (slice 2)
- `docs/ux/j0.md`, `docs/ux/DESIGN.md`, `docs/ux/components.md` §0.3-0.5 + §1.1-1.6 (Sally REFINED v1)
- `docs/personas-jtbd.md` §RBAC Matrix (refined 2026-05-05)
- `docs/architecture-decisions.md` §Authentication & Security
- `docs/openspec-slice.md` row 4

**Out of scope (deferred to later slices)**:
- Dashboard `(app)/+layout.svelte`, Sidebar, `+error.svelte` rendering, theme toggle UI → slice W1.
- `tokens.css` install + Lucide install + Tailwind config → slice W1 (this slice ships the login surface using inline `<style>` blocks referencing the locked OKLCH values until W1 plants the canonical CSS file).
- Lighthouse CI + OpenAPI typegen pipeline → slice 5 `api-foundation-rfc7807`.
- `iguanatrader admin bootstrap-tenant` CLI → slice T4.
- 2FA / MFA / password reset UI → v3 SaaS.
- Per-tenant brand on `(auth)/` → v2 SaaS.

**Dependencies**:
- `persistence-tenant-enforcement` (slice 3) ✅ merged 2026-05-04 PR #55 — provides `users`, `tenants`, `authorized_senders` tables + `tenant_listener` + `tenant_id` ContextVar plumbing.
- `shared-primitives` (slice 2) ✅ merged 2026-05-01 PR #51 — provides `IguanaError` hierarchy + `ContextVar` holders + `time.utc_now`.
- `bootstrap-monorepo` (slice 1) ✅ merged 2026-04-30 PR #22 — provides `apps/api/`, `apps/web/`, pre-commit, CI, dev tooling.

**FRs covered**:
- **FR31** Auth flow (cookie-based JWT session, login/logout/refresh, redirect-to)
- **FR38** Authorized-sender enforcement at the API level (rate-limit + role gating; per-channel sender whitelist is delegated to slice P1 because it's a different identity model — phone numbers / Telegram IDs)

**NFRs covered**:
- **NFR-S3** Encrypted secrets at rest (cookie SECRET_KEY loaded from `.env` per the SOPS strategy in `eligia-secrets-strategy.md`)
- **NFR-S4** Encrypted-channel transport (HTTPS-only cookie via `Secure` flag; documented as conditional on prod environment, dev localhost uses HTTP for ergonomics with `Secure=false` flagged as gotcha)
- **NFR-S5** Anti-brute-force (slowapi 5/min on `/auth/login`)
