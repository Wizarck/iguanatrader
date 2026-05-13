# Retrospective: auth-change-password

- **PR**: [#132](https://github.com/Wizarck/iguanatrader/pull/132) (merged 2026-05-13, squash `bd1cc0c`).
- **Archive path**: `openspec/changes/archive/2026-05-13-auth-change-password/`
- **Lines shipped**: 1415 insertions / 4 deletions across 21 files. CI green on first push.

## What worked

- **Server-side `must_change_password` middleware (`apps/api/src/iguanatrader/api/middleware/must_change_password.py`)** — gate runs before any handler, redirects to `/account/change-password` for any non-whitelisted route. Whitelist is the change-password endpoint itself + `/healthz` + the logout route — minimal surface. Eliminates the "user sees something stale before forced rotation" race.
- **Argon2id `verify_password` for old-password proof** reuses the same hashing layer as login (`apps/api/src/iguanatrader/api/auth.py`). No duplicate logic; the unit test verifies the equivalence.
- **Alembic migration `0013_user_password_metadata.py`** (`must_change_password BOOLEAN NOT NULL DEFAULT FALSE` + `password_changed_at TIMESTAMP NULL`) followed by an offline backfill of existing users — `must_change_password=False` for legacy users (they already self-set their password), `password_changed_at=NOW()` so subsequent rotations have a baseline.
- **Svelte change-password page (`apps/web/src/routes/(app)/account/change-password/+page.svelte`)** uses the existing form pattern + OKLCH dark theme — copy-paste-extend from the login page kept it free of style drift.
- **Form-level (not field-level) error rendering** — backend returns RFC 7807 `detail` + `error_code`; the page renders one `<div class="error" role="alert">` per submission failure. Avoids the 4-field-different-errors UI smell.

## What didn't

- **First-attempt routing of the redirect target** in the middleware — I initially redirected to `/account/change-password?force=1` which bled the gate into the URL, then realised the page itself is unconditional + the `must_change_password` flag on the session is the single source of truth. Cleaned up before push. Pre-flag: never encode security state in URL query strings — it makes the URL bookmarkable + the bookmarked state diverges from the DB.
- **Migration backfill timing in test conftest** — first version of `conftest.py` ran the migration *after* user fixture creation, so the new columns didn't exist when the user was inserted → fixture error. Fixed by re-ordering migrations to run before all fixtures. Pre-flag: in `apps/api/tests/integration/conftest.py`, every test-DB-state change must run before the first user fixture, NOT inline with it.

## Carry-forward

- **Password complexity requirements** — current validation is "different from old + ≥8 chars" via Pydantic. A real policy (lowercase + uppercase + digit + symbol) is an operator decision; defer until a real opinion lands.
- **`password_changed_at` aging warning** — surface "your password is N days old, rotate?" banner once `password_changed_at < NOW() - 90d`. Tactical follow-up.
- **`/account` route as a settings hub** — currently `/account/change-password` is the only `/account/*` page; future `/account/profile`, `/account/sessions`, `/account/audit` slot in here.
- **Force-rotation via admin CLI** — operators may want to force a specific user to rotate on next login (e.g., post-incident). `iguanatrader admin force-password-rotation --email ...` is a small follow-up.

## Pattern usage

- **Middleware ordering matters** — `must_change_password` runs AFTER authn (it needs the user object) but BEFORE any route. Document this in the middleware module's docstring + the route comments.
- **Pydantic field validators for password rules** centralise rule changes — `ChangePasswordIn.validate_new_password` is the single spot to extend without touching route code or tests.
- **RFC 7807 problem responses** for password-rotation errors keep the API surface uniform with the rest of the auth flow.
