# Tasks: auth-forgot-password-flow

> Both prerequisite slices (`auth-change-password` PR #132 + `channel-email-adapter` PR #131) merged to main.

- [ ] 1. Alembic migration `0014_user_recovery_channels.py` — adds `users.telegram_chat_id VARCHAR(64) NULL` + `users.whatsapp_phone VARCHAR(32) NULL`
- [ ] 2. `apps/api/src/iguanatrader/persistence/models.py` — extend `User` ORM model with the two new columns
- [ ] 3. `apps/api/src/iguanatrader/api/auth/temp_password.py` (or wherever `hash_password` lives) — `generate_temp_password() -> str` (16 chars, base32 no-confusables, formatted `XXXX-XXXX-XXXX-XXXX`)
- [ ] 4. `apps/api/src/iguanatrader/shared/channel_dispatch/recipients.py` (NEW) — `resolve_recipients_for_user(user) -> Sequence[Recipient]` (email + optional telegram + whatsapp)
- [ ] 5. `apps/api/src/iguanatrader/contexts/approval/dispatcher.py::resolve_recipients_from_request` — delegate to the new helper
- [ ] 6. `apps/api/src/iguanatrader/api/dtos/auth.py` — add `ForgotPasswordRequest` + `ForgotPasswordResponse` Pydantic models
- [ ] 7. `apps/api/src/iguanatrader/api/routes/auth.py` — `POST /api/v1/auth/forgot-password` endpoint with `@limiter.limit("3/hour")` + anti-enumeration + dispatcher fan-out
- [ ] 8. `apps/api/tests/integration/test_forgot_password.py` — 6 cases
- [ ] 9. `apps/api/tests/unit/api/test_temp_password_generator.py` — 3 cases (entropy, alphabet, format)
- [ ] 10. `apps/api/tests/unit/shared/channel_dispatch/test_recipients.py` — 4 cases
- [ ] 11. `apps/web/src/routes/(auth)/forgot-password/+page.svelte` + `+page.server.ts` — form + generic success view
- [ ] 12. `apps/web/src/routes/(auth)/login/+page.svelte` — add link to `/forgot-password`
- [ ] 13. `docker-compose.mvp.yml` — extend `api.environment:` with the 10 channel/SMTP env vars (all `${VAR:-}`)
- [ ] 14. `docs/mvp-deploy.md` — Step 2 extended with channel env vars + SOPS rename note + DNS prerequisites + selector explanation
- [ ] 15. ruff + black + mypy --strict + pytest verde locally
- [ ] 16. Vitest + svelte-check verde locally
- [ ] 17. Push + open PR (pre-populate §4.5 in body from the start so `ai-self-review-required` is green on first eval)
- [ ] 18. Wait for CI 15/15 green before reporting back
