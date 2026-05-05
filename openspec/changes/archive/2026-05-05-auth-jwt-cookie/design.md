## Context

Slice 4 is the first slice in Wave 0 that ships a UI surface. It plants the auth contract that **every** post-Wave-0 slice depends on for identity propagation:
- `requires_role(...)` decorator is reused by all `/api/v1/*` mutating endpoints (T4 trading routes, K1 risk routes, R5 research refresh, etc.).
- `tenant_id` ContextVar (set by `get_current_user` dependency) is the linchpin for the SQLAlchemy `tenant_listener` (slice 3) — without it, the listener has no tenant to inject and queries fail-closed with no rows.
- The cookie + redirect-to allow-listing contract is what slice W1 will extend in `hooks.server.ts` to gate the `(app)` route group.

Wave 0 cumulative state at slice-4 start:
- Slice 1 `bootstrap-monorepo` ✅ — `apps/api/`, `apps/web/`, pre-commit, CI baseline.
- Slice 2 `shared-primitives` ✅ — `IguanaError` hierarchy, ContextVar holders, `time.utc_now`, structlog config base.
- Slice 3 `persistence-tenant-enforcement` ✅ — SQLAlchemy + Alembic + `tenant_listener` + `users`/`tenants`/`authorized_senders` tables.

The UX contract for the auth surface was locked 2026-05-05 (Sally + Arturo). Canonical references:
- `docs/ux/j0.md` — auth + error surfaces walkthrough.
- `docs/ux/DESIGN.md` §1 — locked OKLCH tokens.
- `docs/ux/components.md` §0.3 (tokens), §0.5 (Lucide iconography), §1.1 (Button), §1.4 (Input), §1.9 (Alert).
- `docs/personas-jtbd.md` §RBAC Matrix (refined 2026-05-05) — single-seat-per-tenant; `tenant_user` is admin of their tenant.

## Goals / Non-Goals

**Goals:**
- Plant the canonical JWT-cookie session contract usable by every post-Wave-0 API endpoint.
- Wire the `tenant_id` + `user_id` ContextVar propagation that slice 3's `tenant_listener` requires.
- Ship a working `/login` surface that visually matches the locked Sally mock at `docs/ux/variants/mock-c3-auth-surfaces.html`.
- Deliver the `requires_role(tenant_user)` and `requires_role(god_admin)` factory primitives so later slices declare RBAC at route level.
- Anchor anti-brute-force (slowapi 5/min) at the app factory level so other endpoints reuse the limiter.

**Non-Goals:**
- Dashboard skeleton (`(app)/+layout.svelte`, Sidebar, KillSwitchButton wiring) → slice W1.
- `+error.svelte` rendering (404/500/401 surfaces) → slice W1; this slice only commits the cookie hook that triggers the 302 redirect to `/login`.
- Tailwind `tokens.css` install + Lucide install + theme toggle UI → slice W1.
- 2FA / MFA / password reset UI → v3 SaaS.
- Per-tenant brand customisation on `(auth)/` → v2 SaaS.
- `iguanatrader admin bootstrap-tenant <slug>` CLI command → slice T4.
- Cross-tenant `god_admin` impersonation banner UI → v2 SaaS (the JWT claim shape is forward-compatible; the UI surface that reads it lands later).

## Decisions

### D1. JWT signing: HS256 with single rotating secret (not RS256)

**Decision**: HS256 with a single secret loaded from `IGUANATRADER_JWT_SECRET` env var, ≥32 bytes. The secret is derived from SOPS-encrypted env (per `eligia-secrets-strategy.md`) at deploy time.

**Alternatives considered**:
- RS256 (asymmetric): irrelevant for MVP single-process FastAPI; key rotation complexity + larger tokens for zero benefit when API and identity provider are the same process.
- ES256 (EC): same trade-off as RS256, slightly faster verify but unjustified complexity.

**Rationale**: single-process, single-trust-domain → symmetric is the right primitive. We pay extra at v2 multi-tenant SaaS only if we need cross-process verification (distinct service for identity vs API), which is a future architectural call.

### D2. Cookie config

**Decision**:
- Name: `iguana_session`.
- Flags: `HttpOnly=true`, `Secure=true` in prod (NFR-S4); `Secure=false` in dev with explicit `IGUANATRADER_DEV_INSECURE_COOKIE=1` flag (documented gotcha — cannot be set without the flag).
- `SameSite=Strict` (per `architecture-decisions.md` §Authentication & Security).
- `Max-Age` = 7 days (sliding lifetime; refreshed on every authenticated request via `/auth/refresh` rotation, NOT via mutating the cookie on each request — that would explode write contention).
- `Domain` unset (default = exact host); `Path=/`.

**Alternatives considered**:
- `SameSite=Lax`: would allow some cross-site GETs that we do not want (no third-party embed scenarios in MVP).
- `SameSite=None`: requires `Secure=true` always, breaks dev localhost ergonomics.

**Risk**: SameSite=Strict will block the user from following an external link to a deep-linked dashboard URL while authenticated — the cookie won't be sent. Mitigation: documented gotcha; the workaround is "navigate to `/` first then to the deep link" which is acceptable for an internal tool.

### D3. Session strategy: 7-day sliding cookie + 24h JWT + refresh-on-demand rotation

**Decision**:
- Cookie `Max-Age` = 7 days (the "session lifetime" as visible to the user).
- JWT `exp` claim = 24h (the "active token lifetime").
- Refresh strategy: when a request arrives with a JWT whose `exp` is within 30 minutes of expiry, `get_current_user` calls `_rotate_token` which issues a new JWT with a fresh 24h expiry and Set-Cookie's it on the response. No separate `/auth/refresh` polling required from the client.
- Hard ceiling: cookie `Max-Age` is NOT extended by rotation — the 7-day clock is from initial login, period. After 7 days the user MUST re-authenticate.

**Alternatives considered**:
- Pure 7-day JWT: blast radius of a stolen JWT is 7 days. Too long.
- Pure 1h JWT + explicit refresh tokens: refresh tokens require their own table, rotation, revocation list. Overkill for single-user MVP.

**Rationale**: 24h JWT keeps the blast radius of a leak short while the 7d hard ceiling matches the user's expectation of "log in weekly". Auto-rotation removes the client-side complexity of handling 401-then-refresh dance.

### D4. Argon2id parameters (defensive but not paranoid)

**Decision**:
- `time_cost`: 3 iterations.
- `memory_cost`: 65536 KiB (64 MiB).
- `parallelism`: 4.
- `hash_len`: 32 bytes.
- `salt_len`: 16 bytes.
- Library: `argon2-cffi` (the canonical Python binding; OWASP-recommended).

These are the OWASP 2024 minimum recommendations + 2× memory headroom. Single-host MVP can absorb the latency (~80ms per verify on Arturo's hardware).

**Alternatives considered**:
- bcrypt: legacy, no GPU resistance.
- scrypt: solid but Argon2id is the modern preference; single library handle is simpler.

**Documented gotcha** (in `docs/gotchas.md`): if memory_cost is increased later, stored hashes still verify (Argon2id encodes parameters into the hash); INCREASING params is forward-compatible.

### D5. Rate-limiter scope: per-IP + per-email

**Decision**: slowapi 5/min on `/auth/login` keyed by `(ip, email)` tuple. The compound key prevents a single attacker from exhausting the limit for a victim email by spamming guesses against a single IP.

**Alternatives considered**:
- Per-IP only: vulnerable to victim-email DoS (attacker burns the limit for the target).
- Per-email only: vulnerable to distributed attacks across many IPs.

**Trade-off**: a NAT'd network with multiple legitimate users sharing an IP would see them mutually limited. MVP is single-user, so non-issue. v2 SaaS will need to revisit if multi-user scenarios emerge.

### D6. First-tenant bootstrap: refuse with helpful 503

**Decision**: when `tenants` table has 0 rows, `POST /auth/login` returns `503 Service Unavailable` with RFC 7807 Problem Detail body:

```json
{
  "type": "https://iguanatrader.local/problems/not-bootstrapped",
  "title": "iguanatrader has no tenants yet",
  "status": 503,
  "detail": "Run `iguanatrader admin bootstrap-tenant <slug>` to create the first tenant + admin user."
}
```

**Alternatives considered**:
- Auto-create from first login (Heroku-style): tempting but couples auth to provisioning, which is a slice T4 concern. Bootstrap is an explicit operator action.
- 401 Unauthorized: technically wrong; the request is well-formed but the resource doesn't exist yet.

The CLI command lands in slice T4. Until then, integration tests use a pytest fixture that seeds a tenant + user directly via SQLAlchemy.

### D7. ContextVar propagation timing

**Decision**: `get_current_user` FastAPI dependency sets `tenant_id` and `user_id` ContextVars **before** any database operation runs. Order of operations inside the dependency:

1. Read cookie → decode JWT → load user + tenant from DB.
2. Set `tenant_id_ctx.set(user.tenant_id)`.
3. Set `user_id_ctx.set(user.id)`.
4. Set `correlation_id_ctx.set(request.headers.get('X-Correlation-ID') or uuid4())`.
5. Return `User` model.

The DB load in step 1 happens with `tenant_id_ctx` UNSET — this is intentional. The `tenant_listener` (slice 3) checks for the ContextVar's presence; absent ContextVar = the listener applies NO filter (this is the bootstrap path used by the loader itself, by Alembic, and by the JSON1 verify on boot). Once step 2 runs, all subsequent queries within the request are tenant-isolated.

**Risk**: if a developer adds a query inside `get_current_user` BEFORE step 2 expecting tenant isolation, they get the wrong behaviour. Mitigation: the helper has a single SELECT (the user lookup by JWT subject), and a comment in the code documents the bootstrap-vs-isolated boundary. Documented in `docs/gotchas.md`.

### D8. SvelteKit form action vs JSON fetch from client

**Decision**: the `/login` form is a SvelteKit **form action** (server-side handler in `+page.server.ts`), NOT a JSON fetch from `+page.svelte`.

**Rationale**:
- Form actions work without JavaScript (progressive enhancement).
- The form action runs on the SvelteKit server, which proxies to the FastAPI backend. This means cookies set by the FastAPI response come from the same origin as the page (SvelteKit's host), avoiding the SameSite=Strict third-party cookie problem.
- CSP-friendly: no inline scripts needed.

**Alternative considered**: client-side `fetch` to FastAPI. Forced cross-origin cookie handling complications and breaks no-JS users. Rejected.

### D9. Redirect-to allow-listing

**Decision**: `redirect_to` query param is allow-listed at the SvelteKit form action level: only same-origin paths (`startsWith('/')` AND NOT `startsWith('//')` AND NOT contains `://`). Any other value falls back to `/`.

This prevents open-redirect phishing where an attacker crafts `https://localhost/login?redirect_to=https://evil.com` and the post-auth redirect lands the user on the attacker's page.

### D10. `requires_role` factory shape

**Decision**:
```python
def requires_role(*roles: Role) -> Callable[[User], User]:
    """FastAPI dependency factory that gates a route to one of the given roles."""
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="role mismatch")
        return user
    return _dep
```

Usage:
```python
@router.post("/strategies/{id}/config")
async def update_strategy(
    id: UUID, body: StrategyConfig,
    user: User = Depends(requires_role(Role.tenant_user)),
):
    ...
```

The role enum has two members in MVP: `tenant_user` and `god_admin`. The `god_admin` is reserved for platform routes (none in MVP/v2 surfaces; CLI-only via direct DB).

## Risks / Trade-offs

- **[Risk] Cookie SameSite=Strict blocks deep-link from external apps** → Mitigation: documented gotcha; deep-link via Telegram → "open dashboard" CTA opens the home (`/`) and re-navigates. Internal-tool acceptable.
- **[Risk] Argon2id memory_cost (64 MiB) on a constrained host** → Mitigation: single-user MVP host has ≥8 GiB; documented as a tunable in `docs/gotchas.md`. Future v2 multi-tenant SaaS may need to lower memory_cost or move auth to a dedicated host.
- **[Risk] JWT secret leak invalidates all sessions** → Mitigation: rotation procedure documented in `docs/runbooks/auth-secret-rotation.md` (creating it as part of this slice). Rotation = bump `IGUANATRADER_JWT_SECRET` env, restart API; all existing cookies become invalid → users redirected to `/login` (the 401 expired flow handles this gracefully).
- **[Risk] First-tenant 503 confuses early users running iguanatrader for the first time** → Mitigation: the Problem Detail response body explicitly names the CLI command they need to run. Plus README onboarding step documents "first run".
- **[Risk] Redirect-to allow-list bypass via Unicode tricks (e.g., `\\evil.com`)** → Mitigation: the validator rejects any value containing `://`, `//`, `\` or starting with anything other than `/` followed by an alphanumeric. Test coverage in `test_auth_flow.py::test_redirect_to_allowlist_*`.
- **[Risk] Slice 5 `api-foundation-rfc7807` will refactor router registration to dynamic discovery** → Mitigation: this slice's `app.py` modification is a pre-pattern; the slice 5 follow-up is filed in `proposal.md` Impact section. The refactor is a one-line change (replace manual `app.include_router(auth_router)` with the dynamic loop).
- **[Trade-off] No CSRF token in MVP**: the form action is same-origin, SameSite=Strict cookie blocks cross-site form submission, and JSON endpoints require the cookie which won't travel cross-site. CSRF token is conventional belt-and-suspenders; for single-user MVP we accept the slight risk reduction in exchange for less form-handling complexity. Documented as a v2 SaaS revisit.

## Migration Plan

This slice has no prior auth contract to migrate from. Deployment is greenfield: bump version, run Alembic (no new migrations from this slice — slice 3 already shipped the schema), deploy. Rollback = revert PR; no schema changes to undo.

## Open Questions

(none open at design time; all resolved during the Sally pass for UX surface contract and during this design review for backend semantics. Implementation may surface open questions which land as PR comments + tasks.md updates.)
