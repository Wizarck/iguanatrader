## ADDED Requirements

### Requirement: Login authenticates a user against Argon2id-hashed credentials

The system SHALL accept email + password credentials at `POST /api/v1/auth/login`, verify the password against the stored Argon2id hash for that email's `User` row scoped to a single tenant, and on success issue a signed JWT (HS256, 24h expiry) embedded in an `iguana_session` HTTP cookie (`HttpOnly`, `SameSite=Strict`, `Secure` in production, 7-day `Max-Age`).

#### Scenario: Successful login

- **WHEN** a `POST /api/v1/auth/login` request arrives with a valid email + password matching a stored `User` row
- **THEN** the response is `200 OK` with body `{"redirect_to": "<allow-listed-path>"}`
- **AND** `Set-Cookie: iguana_session=<jwt>; HttpOnly; Secure; SameSite=Strict; Max-Age=604800; Path=/` is present
- **AND** the structlog event `auth.login.success` is emitted with `tenant_id`, `user_id`, `correlation_id`

#### Scenario: Wrong password

- **WHEN** a `POST /api/v1/auth/login` request arrives with a valid email but the password fails Argon2id verify
- **THEN** the response is `401 Unauthorized` with RFC 7807 Problem Detail body
- **AND** no `Set-Cookie` header is returned
- **AND** the structlog event `auth.login.failure` is emitted with `email_hash` (NOT the email) and `correlation_id`
- **AND** the response body does NOT distinguish "user not found" from "wrong password" (uniform error to defeat user enumeration)

#### Scenario: Email not found

- **WHEN** a `POST /api/v1/auth/login` request arrives with an email that has no corresponding `User` row
- **THEN** the response is `401 Unauthorized` (same shape as wrong-password)
- **AND** an Argon2id verify is run against a dummy hash anyway (timing-attack mitigation — verify time is constant regardless of user existence)

#### Scenario: First-tenant bootstrap not yet performed

- **WHEN** a `POST /api/v1/auth/login` request arrives and the `tenants` table has zero rows
- **THEN** the response is `503 Service Unavailable` with RFC 7807 Problem Detail body
- **AND** the body's `type` is `https://iguanatrader.local/problems/not-bootstrapped`
- **AND** the body's `detail` includes the CLI command "Run `iguanatrader admin bootstrap-tenant <slug>` to create the first tenant + admin user."

### Requirement: Login is rate-limited to 5 attempts per minute per (IP, email) tuple

The system SHALL apply slowapi rate-limiting to `POST /api/v1/auth/login` keyed on the compound `(client_ip, email)` tuple. Exceeding the limit SHALL return `429 Too Many Requests` with a `Retry-After: <seconds>` header.

#### Scenario: 6th attempt within 60s

- **WHEN** the same `(ip, email)` tuple has issued 5 `POST /api/v1/auth/login` requests within the last 60 seconds
- **AND** a 6th request arrives
- **THEN** the response is `429 Too Many Requests` with header `Retry-After: <seconds-until-window-resets>`
- **AND** the response body is RFC 7807 Problem Detail with `type: rate-limited`
- **AND** Argon2id verify is NOT executed (limiter rejects before reaching the auth handler)
- **AND** the structlog event `auth.login.rate_limited` is emitted

#### Scenario: Different email under same IP within window

- **WHEN** the limit is exhausted for `(ip_X, email_A)`
- **AND** a request arrives for `(ip_X, email_B)` (different email, same IP)
- **THEN** the request is processed normally (limit is per-tuple, not per-IP alone)

### Requirement: Authenticated requests propagate tenant + user identity via ContextVars

The system SHALL provide a FastAPI dependency `get_current_user` that reads the `iguana_session` cookie, decodes the JWT, loads the corresponding `User` row, and sets `tenant_id_ctx`, `user_id_ctx`, and `correlation_id_ctx` ContextVars before returning. The ContextVars SHALL be set BEFORE any subsequent database operation in the request lifecycle.

#### Scenario: Valid cookie + valid JWT

- **WHEN** a request arrives with a valid `iguana_session` cookie carrying a JWT whose `exp` claim is in the future
- **AND** the JWT's `sub` claim corresponds to an existing `User` row
- **THEN** `get_current_user` returns the `User` model
- **AND** `tenant_id_ctx.get()` returns the user's `tenant_id`
- **AND** `user_id_ctx.get()` returns the user's `id`
- **AND** any subsequent SQLAlchemy query inside the request body is filtered by `tenant_listener` to that `tenant_id`

#### Scenario: Missing cookie

- **WHEN** a request to a route protected by `get_current_user` arrives with no `iguana_session` cookie
- **THEN** the response is `401 Unauthorized` with RFC 7807 Problem Detail
- **AND** ContextVars are not set

#### Scenario: Expired JWT

- **WHEN** a request arrives with a cookie carrying a JWT whose `exp` claim is in the past
- **THEN** the response is `401 Unauthorized`
- **AND** the structlog event `auth.session.expired` is emitted

#### Scenario: Tampered JWT

- **WHEN** a request arrives with a cookie carrying a JWT whose signature does not verify against `IGUANATRADER_JWT_SECRET`
- **THEN** the response is `401 Unauthorized`
- **AND** the structlog event `auth.session.invalid_signature` is emitted (no `user_id` field — the token is untrusted)

### Requirement: JWTs are auto-rotated on requests within 30 minutes of expiry

When a request arrives with a JWT whose `exp` claim is within 30 minutes of the current time, `get_current_user` SHALL issue a new JWT (with a fresh 24h expiry) and emit a `Set-Cookie` header on the response. The cookie's `Max-Age` SHALL NOT be extended — the 7-day session ceiling from initial login is hard.

#### Scenario: JWT near expiry rotates silently

- **WHEN** a request arrives with a JWT whose `exp` is 25 minutes from now
- **AND** the JWT is otherwise valid
- **THEN** the request proceeds (200 OK with the route's normal response)
- **AND** the response carries `Set-Cookie: iguana_session=<new-jwt>; <flags>` with the same `Max-Age` budget computed from the ORIGINAL login time (NOT now)
- **AND** the structlog event `auth.session.rotated` is emitted

#### Scenario: 7-day cookie ceiling reached

- **WHEN** a request arrives with a valid JWT but the cookie's effective `Max-Age` is exhausted (originating login was ≥7 days ago)
- **THEN** the response is `401 Unauthorized`
- **AND** the structlog event `auth.session.ceiling_reached` is emitted

### Requirement: Logout invalidates the cookie

The system SHALL provide `POST /api/v1/auth/logout` that returns `200 OK` and clears the `iguana_session` cookie via `Set-Cookie: iguana_session=; Max-Age=0; ...same-flags`.

#### Scenario: Authenticated logout

- **WHEN** an authenticated user calls `POST /api/v1/auth/logout`
- **THEN** the response is `200 OK`
- **AND** the response carries a `Set-Cookie` header that clears `iguana_session` (Max-Age=0, empty value)
- **AND** the structlog event `auth.logout` is emitted with `tenant_id`, `user_id`

#### Scenario: Unauthenticated logout

- **WHEN** an unauthenticated request calls `POST /api/v1/auth/logout`
- **THEN** the response is `200 OK` (idempotent — clearing an absent cookie is a no-op)
- **AND** no structlog event is emitted

### Requirement: `GET /api/v1/auth/me` returns the current user payload

The system SHALL provide `GET /api/v1/auth/me` returning the authenticated user's safe payload: `{user_id, tenant_id, email, role, created_at}`. Sensitive fields (`password_hash`, internal flags) SHALL NEVER appear in the response.

#### Scenario: Authenticated /me

- **WHEN** an authenticated request calls `GET /api/v1/auth/me`
- **THEN** the response is `200 OK` with body `{"user_id": "...", "tenant_id": "...", "email": "...", "role": "tenant_user", "created_at": "<ISO 8601 UTC>"}`
- **AND** the response body contains NO `password_hash` field

#### Scenario: Unauthenticated /me

- **WHEN** an unauthenticated request calls `GET /api/v1/auth/me`
- **THEN** the response is `401 Unauthorized`

### Requirement: SvelteKit `(auth)/login` form action proxies to FastAPI and sets the cookie at the SvelteKit origin

The SvelteKit application SHALL provide `apps/web/src/routes/(auth)/login/+page.server.ts` exporting a form action that POSTs the credentials to FastAPI's `/api/v1/auth/login`, propagates the resulting `Set-Cookie` to the user-agent at the SvelteKit origin, and 302-redirects to the allow-listed `redirect_to` (or `/` if absent / not allow-listed).

#### Scenario: Successful login from form action

- **WHEN** the user submits the login form with valid credentials
- **AND** `redirect_to` query param is `/portfolio?range=last-7d`
- **THEN** the form action POSTs to FastAPI, receives 200 + Set-Cookie
- **AND** the form action returns a 302 redirect to `/portfolio?range=last-7d`
- **AND** the user-agent receives the `iguana_session` cookie at the SvelteKit origin

#### Scenario: redirect_to is not allow-listed

- **WHEN** the form action receives a `redirect_to` value that is `https://evil.com/phish`, or `//evil.com`, or any path not starting with a single `/`
- **THEN** the redirect target falls back to `/`
- **AND** the structlog event `auth.login.redirect_rejected` is emitted with the rejected value

#### Scenario: 429 from FastAPI rate-limiter

- **WHEN** the form action receives a 429 response with `Retry-After: <seconds>`
- **THEN** the form rerenders with an `Alert variant="destructive"` containing copy "Rate limit reached. Wait <N>s before retrying."
- **AND** the submit Button is rendered as `disabled`
- **AND** a JS-side countdown ticks down the `<N>` value (form action returns the seconds; client uses `setInterval` to update the label)

### Requirement: SvelteKit cookie hook gates the `(app)` route group

The SvelteKit application SHALL provide `apps/web/src/hooks.server.ts` that, on every request to a route inside the `(app)` route group, reads the `iguana_session` cookie and validates it via FastAPI's `/api/v1/auth/me`. On absent / invalid / expired cookie, it SHALL 302-redirect to `/login?redirect_to=<originating-path>`.

#### Scenario: Authenticated request to (app) route

- **WHEN** a request to `/portfolio` arrives with a valid `iguana_session` cookie
- **THEN** `hooks.server.ts` calls `/api/v1/auth/me`, receives 200, attaches the user to `event.locals.user`
- **AND** the request proceeds to the `(app)` route

#### Scenario: Unauthenticated request to (app) route

- **WHEN** a request to `/portfolio?range=last-7d` arrives with no cookie
- **THEN** `hooks.server.ts` returns a 302 redirect to `/login?redirect_to=%2Fportfolio%3Frange%3Dlast-7d`
- **AND** the user-agent's URL bar updates to `/login?redirect_to=...`

#### Scenario: Cookie present but JWT expired

- **WHEN** a request to `/portfolio` arrives with a cookie whose JWT is expired
- **THEN** `hooks.server.ts` calls `/api/v1/auth/me`, receives 401
- **AND** the SvelteKit response is a 302 redirect to `/login?redirect_to=%2Fportfolio`
- **AND** the rendered login page displays an `Alert variant="info"` with copy "Your session ended. Sign in again to resume."

### Requirement: Role gating via `requires_role` factory

The system SHALL provide a `requires_role(*roles: Role) -> Callable` factory dependency that gates routes by role membership. Routes guarded by `requires_role(Role.tenant_user)` SHALL accept any authenticated tenant user; routes guarded by `requires_role(Role.god_admin)` SHALL accept only platform-level admins (no UI surface in MVP/v2 — CLI ops only).

#### Scenario: tenant_user accessing operational route

- **WHEN** an authenticated `tenant_user` calls a route guarded by `requires_role(Role.tenant_user)`
- **THEN** the request proceeds normally

#### Scenario: tenant_user accessing god_admin route

- **WHEN** an authenticated `tenant_user` calls a route guarded by `requires_role(Role.god_admin)`
- **THEN** the response is `403 Forbidden` with RFC 7807 Problem Detail
- **AND** the structlog event `auth.role.mismatch` is emitted with the user's actual role and the route's required role

#### Scenario: Unauthenticated request to gated route

- **WHEN** an unauthenticated request calls a route guarded by any `requires_role(...)` 
- **THEN** the response is `401 Unauthorized` (the underlying `get_current_user` dependency rejects before role check)

### Requirement: Argon2id parameters are documented and tunable

The Argon2id password hashing parameters SHALL be: `time_cost=3`, `memory_cost=65536` (KiB), `parallelism=4`, `hash_len=32`, `salt_len=16`. The parameters SHALL be defined in a single module-level constant in `apps/api/src/iguanatrader/api/auth.py` and overridable via env (`IGUANATRADER_ARGON2_MEMORY_KIB` etc.) for tuning on constrained hosts.

#### Scenario: Default parameters used

- **WHEN** no Argon2 env override is set
- **AND** a new password is hashed
- **THEN** the resulting hash encodes `t=3,m=65536,p=4` parameters (visible in the standard Argon2 hash format prefix `$argon2id$v=19$m=65536,t=3,p=4$...`)

#### Scenario: Increasing memory_cost preserves verification of older hashes

- **WHEN** a hash was stored with `memory_cost=65536`
- **AND** the env var `IGUANATRADER_ARGON2_MEMORY_KIB=131072` is set on a later boot
- **AND** a verify is attempted against the old hash with the original password
- **THEN** the verify succeeds (Argon2id encodes parameters into the hash; the lib uses the encoded params for verify, NOT the env params)
