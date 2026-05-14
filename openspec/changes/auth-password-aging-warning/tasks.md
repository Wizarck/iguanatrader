# Tasks: auth-password-aging-warning

- [ ] 1. `apps/api/src/iguanatrader/api/deps.py` — extend `AuthenticatedUser` dataclass with `password_age_days: int | None` + `password_aging_state: Literal["fresh", "ageing", "stale"]`. Add classifier helper + env-var-driven thresholds.
- [ ] 2. `apps/api/src/iguanatrader/api/dtos/auth.py::MeOut` — add the two new fields with sensible defaults.
- [ ] 3. `apps/api/src/iguanatrader/api/routes/auth.py::me_endpoint` — pass the new fields through.
- [ ] 4. `apps/api/tests/unit/api/test_deps_password_aging.py` — 5 unit tests per proposal.
- [ ] 5. `apps/api/tests/integration/test_me_endpoint.py` (or new file) — 1 integration test exercising the wire-up.
- [ ] 6. `apps/web/src/lib/components/PasswordAgeingBanner.svelte` — new component (proposal markup).
- [ ] 7. `apps/web/src/routes/(app)/+layout.svelte` — mount the banner conditional on `data.me.password_aging_state`.
- [ ] 8. `apps/web/tests/password-ageing-banner.test.ts` — 4 vitest tests per proposal.
- [ ] 9. `docs/configuration.md` (or equivalent) — document the two new env vars.
- [ ] 10. Scoped lint: ruff + black + mypy --strict on touched backend files; svelte-check + vitest on frontend.
- [ ] 11. Local test pass: `pytest` on touched backend tests + `vitest` on touched frontend tests.
- [ ] 12. Push + open PR with §4.5 self-review + canonical AI-reviewer signoff block.
- [ ] 13. STOP after `gh pr create`. Parent monitors CI.
