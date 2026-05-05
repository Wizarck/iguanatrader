# Runbook — rotate `IGUANATRADER_JWT_SECRET`

**Audience**: operator (Arturo / single-host MVP) or platform engineer (v2 SaaS).

**When to run**:

- Routine rotation cadence (suggested: every 90 days, calendar-driven).
- Suspected secret compromise (laptop loss, credential leak, scrub of `git log -p` revealed it accidentally).
- Recovery after a known incident requiring forced re-auth.

**Time budget**: 5–10 minutes including the user-facing re-login.

**Blast radius**: every active session is terminated. All users will be redirected to `/login` on their next request. There is no graceful overlap window in MVP — see `docs/gotchas.md` #26 for context.

---

## 1. Generate a new secret

The secret MUST be at least 32 bytes (`_JWT_SECRET_MIN_BYTES` in `apps/api/src/iguanatrader/api/auth.py`). Generate via Python's `secrets` module so the entropy comes from the OS CSPRNG:

```sh
python -c "import secrets; print(secrets.token_hex(32))"
# → 64 hex chars = 32 bytes
```

Save the value to your password manager BEFORE proceeding. If you lose the new secret between steps 2 and 3 you cannot recover the existing sessions.

## 2. Update the SOPS-encrypted env file

The deployment env files live at `.secrets/dev.env.enc`, `.secrets/paper.env.enc`, `.secrets/live.env.enc` — encrypted with `age` per `docs/operations/eligia-secrets-strategy.md` (TODO once that doc lands; for MVP follow the slice-1 secrets pattern at `.secrets/.sops.yaml`).

```sh
# Decrypt, edit, re-encrypt.
sops .secrets/paper.env.enc
# Inside the editor, replace the line:
#   IGUANATRADER_JWT_SECRET=<old-value>
# with:
#   IGUANATRADER_JWT_SECRET=<new-value-from-step-1>
# Save + exit. SOPS re-encrypts on save.
```

Verify the decrypted view shows the new value:

```sh
sops -d .secrets/paper.env.enc | grep IGUANATRADER_JWT_SECRET
```

Commit the encrypted file:

```sh
git add .secrets/paper.env.enc
git commit -m "chore(secrets): rotate IGUANATRADER_JWT_SECRET"
git push
```

## 3. Restart the API

Pull the new image (or re-source the env on a host-managed deployment) and restart:

```sh
# docker-compose deployment:
docker compose -f docker-compose.paper.yml down api
docker compose -f docker-compose.paper.yml up -d api

# Or, if running directly on the host (uvicorn under systemd):
sudo systemctl restart iguanatrader-api
```

Verify the new value is live:

```sh
docker compose -f docker-compose.paper.yml exec api \
  python -c "import os; print(os.environ['IGUANATRADER_JWT_SECRET'][:8] + '...')"
# → first 8 chars of the new secret
```

## 4. Confirm sessions are invalidated

The expected user-agent flow on the next request:

1. Client sends old cookie → FastAPI `decode_jwt` raises `InvalidSignatureError`.
2. Structlog event `auth.session.invalid_signature` is emitted.
3. FastAPI returns 401.
4. SvelteKit `hooks.server.ts` 302's to `/login?redirect_to=<originating>`.
5. User logs in (with the same email + password — the user table is untouched by this rotation).
6. New JWT signed with the new secret → ride-along resumes.

Tail the logs to confirm:

```sh
docker compose -f docker-compose.paper.yml logs -f api | grep auth.session
```

You should see a burst of `auth.session.invalid_signature` events as users hit their first post-rotation request, followed by `auth.login.success` events as they re-authenticate.

## 5. Sanity-check `/me` with a fresh login

```sh
# Login from a curl session.
curl -s -c /tmp/iguana-cookie.txt \
  -X POST https://iguanatrader.local/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@example.com","password":"<your-password>"}'

# /me round-trips.
curl -s -b /tmp/iguana-cookie.txt https://iguanatrader.local/api/v1/auth/me
# → {"user_id": "...", "tenant_id": "...", "email": "...", "role": "tenant_user", ...}
```

## 6. Notify users (v2 SaaS only)

MVP single-user: skip — Arturo is the only user. v2 SaaS: send an email or in-app banner ahead of the rotation window so users know to expect a re-login. Drafted template lives at `docs/runbooks/templates/auth-rotation-notice.md` (TBD).

---

## Rollback

If step 3 fails (e.g., the API container fails to start because the env file is malformed):

```sh
# Recover the old encrypted file from git.
git checkout HEAD~1 -- .secrets/paper.env.enc
git commit -m "revert: rollback JWT secret rotation"
git push
docker compose -f docker-compose.paper.yml up -d api
```

The old sessions resume working immediately because the old secret is back in env. NO data is lost in the rotation/rollback cycle — the users table, tenant catalogue, and audit log are not touched.

---

## Forward-compat notes

- v2 SaaS multi-tenant may need an overlap window (old + new secret both accepted for verify, only new used for sign). Implementation = `IGUANATRADER_JWT_SECRET_PREVIOUS` env that decode_jwt tries on `InvalidSignatureError` before giving up. Out of scope for MVP.
- Slice T4 lands the `iguanatrader admin rotate-jwt-secret` CLI which automates steps 1–3 + emits a structlog audit event `auth.secret.rotated`. Until then operate manually per this runbook.
