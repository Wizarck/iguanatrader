# Proposal: auth-forgot-password-flow

> **End-user password recovery via the multi-channel dispatcher** — `/login` gets a "¿Olvidaste tu contraseña?" link, the backend generates a temporary password, marks the user with `must_change_password=TRUE`, and fans the credential out over **Email + Telegram + WhatsApp** (whichever channels are wired). First login forces a rotation via the gate from `auth-change-password`. Also wires the dormant Telegram + Hermes adapters into the MVP profile.

## Why

- Today: lose your password → operator runs `bootstrap-tenant --force-reset`, destroys the tenant + all data, recreates from scratch. There is no self-service recovery.
- `auth-change-password` (just merged) gives us the `must_change_password` flag + the `password_changed_at` timestamp. `channel-email-adapter` (just merged) gives us the SMTP transport + branded template.
- The Telegram + Hermes adapters have been shipped since 2026-05-06 but the MVP profile never wired the env vars through. The user flagged "frozen code" as a smell; this slice retires that smell.

## What

### Backend

`apps/api/src/iguanatrader/api/routes/auth.py` extended with:

POST /api/v1/auth/forgot-password
Body: { email: str }
Auth: none

Flow:
1. Look up user by email (case-insensitive). **If not found, still return 200** with the same payload as the success path (anti-enumeration).
2. Generate a 16-char temp password — 4 groups of 4 from a base32 no-confusables alphabet (`A-HJ-NP-Z2-9`), formatted `XXXX-XXXX-XXXX-XXXX`.
3. Hash with `hash_password` (Argon2id).
4. UPDATE `users SET password_hash=:h, must_change_password=TRUE, password_changed_at=:now WHERE id=:uid`.
5. Build an `OutboundMessage` with subject `[iguanatrader] Recuperación de contraseña`, headline `Tu contraseña temporal`, body_html showing the password in a `<p class="creds">` block + ES+EN explanation that it must be changed on next login. Use `render_email_template()` for the HTML body.
6. Resolve recipients from the user record. The user has `email` always; the new columns `telegram_chat_id` + `whatsapp_phone` are nullable opt-in.
7. `await channel_dispatcher.dispatch(message=msg, recipients=recipients)`. Per-channel failure logged but does NOT fail the request.
8. Return 200 with generic message: `{"message": "Si la dirección está registrada, recibirás instrucciones para recuperar la cuenta."}`.

Rate limiting: `slowapi` decorator `@limiter.limit("3/hour")` keyed on remote IP. (Per-email keying needs a custom slowapi key extractor; keep to IP-only to avoid over-engineering.)

### Migration

`apps/api/src/iguanatrader/migrations/versions/0014_user_recovery_channels.py`:

ALTER TABLE users ADD COLUMN telegram_chat_id VARCHAR(64) NULL;
ALTER TABLE users ADD COLUMN whatsapp_phone   VARCHAR(32) NULL;

Both operator-set (no UI in this slice; admin updates via SQL or future CLI).

### MVP wiring (retires dormant Telegram + Hermes adapters)

`docker-compose.mvp.yml` `api.environment:` block extended (all `${VAR:-}` so missing case stays log-only):

```
- IGUANATRADER_CHANNEL_DISPATCHER=${IGUANATRADER_CHANNEL_DISPATCHER:-email}
- IGUANATRADER_SMTP_HOST=${IGUANATRADER_SMTP_HOST:-}
- IGUANATRADER_SMTP_PORT=${IGUANATRADER_SMTP_PORT:-587}
- IGUANATRADER_SMTP_USERNAME=${IGUANATRADER_SMTP_USERNAME:-}
- IGUANATRADER_SMTP_PASSWORD=${IGUANATRADER_SMTP_PASSWORD:-}
- IGUANATRADER_SMTP_FROM_ADDRESS=${IGUANATRADER_SMTP_FROM_ADDRESS:-iguanatrader@palafitofood.com}
- IGUANATRADER_SMTP_FROM_NAME=${IGUANATRADER_SMTP_FROM_NAME:-iguanatrader}
- IGUANATRADER_SMTP_USE_TLS=${IGUANATRADER_SMTP_USE_TLS:-true}
- TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
- HERMES_BASE_URL=${HERMES_BASE_URL:-}
- HERMES_HMAC_SECRET=${HERMES_HMAC_SECRET:-}
```

Default selector is `email`; operator opts into `telegram_hermes_email` by changing one env var. Per-channel fallback to log-only when individual creds missing (already implemented in `build_channel_dispatcher_from_env`).

**SOPS bundle alignment**: `.secrets/dev.env.enc`, `paper.env.enc`, `live.env.enc` currently have `HERMES_WEBHOOK_URL` + `HERMES_AUTH_TOKEN` (legacy from ELIGIA's Hermes). Rename to the canonical `HERMES_BASE_URL` + `HERMES_HMAC_SECRET` that iguanatrader's adapter expects. Operator runs SOPS decrypt + edit + re-encrypt; this slice only updates the env var names in compose + documents the SOPS rename in `docs/mvp-deploy.md`.

### Recipient resolution

Generalise the recipient builder so it works outside the approval context:

- Refactor `apps/api/src/iguanatrader/contexts/approval/dispatcher.py::resolve_recipients_from_request` to extract a smaller helper `resolve_recipients_for_user(user) -> Sequence[Recipient]` in a shared module (e.g., `apps/api/src/iguanatrader/shared/channel_dispatch/recipients.py`). The approval-context resolver delegates to it.
- The new helper reads `user.email`, `user.telegram_chat_id`, `user.whatsapp_phone` and returns the corresponding `Recipient` instances filtered by what's set.

### UI

- `apps/web/src/routes/(auth)/login/+page.svelte` — add a "¿Olvidaste tu contraseña?" link below the submit button → `/forgot-password`.
- `apps/web/src/routes/(auth)/forgot-password/+page.svelte` + `+page.server.ts` — single-input form (email) → form action proxies `POST /api/v1/auth/forgot-password` → success view: "Si la dirección está registrada, recibirás instrucciones por email, Telegram o WhatsApp en los próximos minutos." Same view regardless of match (anti-enumeration).

### Docs

`docs/mvp-deploy.md` — Step 2 extended with:
- `IGUANATRADER_SMTP_*` env vars (with iguanatrader@palafitofood.com as default From)
- `TELEGRAM_BOT_TOKEN` env var
- `HERMES_BASE_URL` + `HERMES_HMAC_SECRET` env vars
- Note about renaming SOPS bundle keys from `HERMES_WEBHOOK_URL` → `HERMES_BASE_URL` etc.
- `IGUANATRADER_CHANNEL_DISPATCHER` selector explanation (default `email`, upgrade to `telegram_hermes_email`)
- DNS prerequisites for `palafitofood.com` SMTP (SPF/DKIM operator-side note)

### Tests

`apps/api/tests/integration/test_forgot_password.py` — 6 cases:
1. Known email → 200 + generic message + `must_change_password=TRUE` + `password_hash` rotated + dispatcher called once.
2. Unknown email → 200 + same generic message + dispatcher NOT called.
3. Rate limit: 4th request within 1h → 429.
4. Email-only fallback when Telegram + WhatsApp creds missing → dispatcher fans to 1 channel (email only).
5. All three channels wired (mock the dispatcher to verify multi-channel fanout) → 3 channels; transport error in one → other two still succeed.
6. After successful recovery, `POST /auth/login` with the temp password works, but `GET /portfolio` returns 403 password-change-required until `change-password` is called.

`apps/api/tests/unit/api/test_temp_password_generator.py` — 3 cases (entropy ≥80 bits, alphabet constraint, format `XXXX-XXXX-XXXX-XXXX`).

`apps/api/tests/unit/shared/channel_dispatch/test_recipients.py` — 4 cases for the new `resolve_recipients_for_user` helper (email-only, +telegram, +whatsapp, all three).

Frontend: 1 vitest for the form-action redirect.

## Out of scope

- Per-user UI for managing recovery channels (Telegram chat-id, WhatsApp phone) — operator sets via SQL or future CLI.
- Recovery via signed-link reset token — chose temp password + force-rotate because Telegram + WhatsApp deliver credentials natively + the `must_change_password` flag already exists.
- Account lockout after N failed login attempts.
- Recovery codes / backup keys.
- `bootstrap-tenant --must-change-password` flag — kept as parent-slice carry-forward.
