# Proposal: auth-change-password

> **Self-service password change for authenticated users** + a `must_change_password` gate so admins can hand out provisional credentials and force a rotation at first login. Foundation slice for `auth-forgot-password-flow`.

## Why

The MVP today has **no in-app password change path**:

- The only way to rotate a password is `iguanatrader admin bootstrap-tenant --force-reset`, which deletes the tenant + all its users + recreates them. Destructive, loses tenant_id + user_id, unusable once the tenant has any data.
- There is no flag on `users` for "this user must change their password on the next login", so `bootstrap-tenant` and any future `forgot-password` flow have nowhere to mark a provisional credential.
- The settings page (`/settings`) only renders feature flags, no security tab.

This slice closes both gaps. The `must_change_password` flag is the load-bearing primitive that `auth-forgot-password-flow` will reuse.

## What

### Migration

`apps/api/src/iguanatrader/migrations/versions/0013_user_password_metadata.py`:

ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP NULL;

`password_changed_at` is set to `NOW()` on every successful hash write (bootstrap, change, force-reset, forgot-password). Useful for audit + future "password too old" policies.

### Backend

`apps/api/src/iguanatrader/api/routes/auth.py` extended with `POST /api/v1/auth/change-password` (body: `{old_password, new_password}`; auth required via session cookie). Flow: verify old via `verify_password`, validate new (min 12 chars, ≥1 digit or symbol, NOT equal to old), hash with `hash_password`, UPDATE row + clear `must_change_password` + set `password_changed_at`. Returns 204.

Errors (RFC 7807):
- `401` `urn:iguanatrader:error:auth-mismatch` — old password wrong.
- `400` `urn:iguanatrader:error:validation` — new password invalid.

### Middleware gate

`apps/api/src/iguanatrader/api/middleware/must_change_password.py`. Runs after auth resolves `request.state.user`. If `user.must_change_password is True` and path NOT in allow-list → 403 `urn:iguanatrader:error:password-change-required`.

Allow-list:
- `POST /api/v1/auth/change-password`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `/healthz`, `/docs`, `/openapi.json`

### UI

- `/account/change-password/+page.svelte` + `+page.server.ts` — form (`old_password`, `new_password`, `confirm`). Form action proxies API; on 204 redirects to `/portfolio`. Shows banner when `?required=1`.
- `/settings/+page.svelte` — add "Security" section ABOVE "Feature flags" with a link to `/account/change-password`.
- `hooks.server.ts` — if `must_change_password=TRUE` on `/auth/me` response, redirect any `(app)` route (except change-password + logout) to `/account/change-password?required=1`.
- Optional: add to TopBar user menu — keep scope minimal, just the settings link is fine.

### Tests

`apps/api/tests/integration/test_change_password.py` — 5 cases:
1. Happy: 204 + flag cleared + hash rotated + password_changed_at set.
2. Old wrong → 401 RFC 7807.
3. New <12 chars → 400.
4. New == old → 400.
5. `must_change_password=TRUE` user gets 403 on `/api/v1/portfolio` until they change.

`apps/api/tests/unit/api/middleware/test_must_change_password.py` — 3 cases (flag off, flag on + allow-list, flag on + gated).

## Out of scope

- forgot-password flow (slice `auth-forgot-password-flow`)
- email adapter (slice `channel-email-adapter`)
- password strength meter / zxcvbn
- 2FA / WebAuthn
- audit_log row for password events
- auto-set must_change_password in bootstrap-tenant
