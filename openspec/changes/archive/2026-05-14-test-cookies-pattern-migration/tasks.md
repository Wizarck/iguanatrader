# Tasks: test-cookies-pattern-migration

- [ ] 1. `apps/api/tests/integration/test_portfolio_routes.py` — replace 23 `cookies={COOKIE_NAME: ...}` call sites with `client.cookies.set` + plain call. Watch for cross-tenant cookie_b in `test_get_*_does_not_leak_other_tenants` / `_returns_empty_for_other_tenant` tests.
- [ ] 2. `apps/api/tests/integration/test_strategies_routes.py` — replace 12 call sites. Cross-tenant block at lines 360-369 needs `client.cookies.set(COOKIE_NAME, cookie_b)` once.
- [ ] 3. `apps/api/tests/integration/test_approval_routes.py` — replace 3 call sites.
- [ ] 4. `apps/api/tests/integration/test_settings_routes.py` — replace 4 call sites.
- [ ] 5. `apps/api/tests/integration/test_trade_routes.py` — replace 5 call sites.
- [ ] 6. Scoped lint: ruff + black on the 5 touched files. (No mypy needed — pure test files; existing strict config covers prod code.)
- [ ] 7. Run pytest locally on the 5 files. Confirm no `DeprecationWarning` escalation. Same pass/fail outcomes as before.
- [ ] 8. Push + open PR with §4.5 self-review.
- [ ] 9. STOP after `gh pr create` returns the PR URL. Parent monitors CI.
