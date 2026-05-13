# Tasks: auth-change-password

- [ ] 1. Alembic migration `0013_user_password_metadata.py` — adds `users.must_change_password BOOLEAN NOT NULL DEFAULT FALSE` + `users.password_changed_at TIMESTAMP NULL`
- [ ] 2. `apps/api/src/iguanatrader/persistence/models/user.py` — extend ORM model
- [ ] 3. `apps/api/src/iguanatrader/api/routes/auth.py` — `POST /api/v1/auth/change-password` endpoint
- [ ] 4. `apps/api/src/iguanatrader/api/routes/auth.py` — extend `GET /auth/me` response with `must_change_password: bool`
- [ ] 5. `apps/api/src/iguanatrader/api/middleware/must_change_password.py` — middleware (allow-list pattern)
- [ ] 6. `apps/api/src/iguanatrader/api/app.py` — register the new middleware AFTER auth middleware
- [ ] 7. `apps/api/src/iguanatrader/api/errors.py` — register the two new URN error types (401 + 403 + 400 variants)
- [ ] 8. `apps/api/tests/integration/test_change_password.py` — 5 cases
- [ ] 9. `apps/api/tests/unit/api/middleware/test_must_change_password.py` — 3 cases
- [ ] 10. `apps/web/src/lib/types.d.ts` (or App.Locals declaration file) — extend `App.Locals['user']` with `must_change_password: boolean`
- [ ] 11. `apps/web/src/hooks.server.ts` — read flag from `/auth/me`; redirect to `/account/change-password?required=1`
- [ ] 12. `apps/web/src/routes/(app)/account/change-password/+page.svelte` + `+page.server.ts`
- [ ] 13. `apps/web/src/routes/(app)/settings/+page.svelte` — add Security section
- [ ] 14. Vitest + svelte-check verde locally
- [ ] 15. ruff + black + mypy --strict + pytest verde locally
- [ ] 16. Push + open PR
- [ ] 17. Wait for CI 15/15 green before reporting back
