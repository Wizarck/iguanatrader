# Tasks: channel-email-adapter

- [x] 1. Add `aiosmtplib` + `jinja2` to root `pyproject.toml` runtime deps; regenerate `poetry.lock` (`poetry lock --no-update` then `poetry lock` to refresh)
- [x] 2. `apps/api/src/iguanatrader/shared/channel_dispatch/adapters/email_smtp.py` — `EmailSMTPDispatcher` + default `_AioSmtpEmailTransport`
- [x] 3. `apps/api/src/iguanatrader/shared/channel_dispatch/templates/email_base.html` — Jinja template with inline CSS, brand mark, accent teal, no-reply disclaimer footer (ES + EN)
- [x] 4. `apps/api/src/iguanatrader/shared/channel_dispatch/templates/__init__.py` — `render_email_template(...)` returns `(html, plain_text)`
- [x] 5. `apps/api/src/iguanatrader/contexts/approval/dispatcher.py::build_channel_dispatcher_from_env` — extend env selector with `telegram_hermes_email` + `email`; per-channel fallback
- [x] 6. `apps/api/src/iguanatrader/shared/channel_dispatch/__init__.py` — export `EmailSMTPDispatcher`, `EMAIL_CHANNEL`, `EMAIL_DEFAULT_RATE_PER_SECOND`, `render_email_template`
- [x] 7. `apps/api/tests/unit/shared/channel_dispatch/test_email_adapter.py` — 5 cases
- [x] 8. `apps/api/tests/unit/shared/channel_dispatch/test_email_template.py` — 4 cases
- [x] 9. `apps/api/tests/property/test_channel_dispatch_isolation.py` — extend to cover Email
- [x] 10. `apps/api/tests/integration/contexts/approval/test_channel_dispatcher_binding.py` — add `telegram_hermes_email` case
- [x] 11. ruff + black + mypy --strict + pytest verde locally
- [ ] 12. Push + open PR
- [ ] 13. Wait for CI 15/15 green before reporting back
