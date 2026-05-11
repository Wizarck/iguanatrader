# Tasks: p1-channel-fanout-production

Linear order; each task ships independently testable.

## Layer 1 — Generic core (shared/channel_dispatch/)

- [ ] 1. Create `shared/channel_dispatch/__init__.py` (empty)
- [ ] 2. Create `shared/channel_dispatch/types.py` — `OutboundMessage`, `Recipient`, `DispatchResult`
- [ ] 3. Create `shared/channel_dispatch/protocol.py` — `MessageDispatcher`, `OutboundTransport` Protocols
- [ ] 4. Create `shared/channel_dispatch/log_only.py` — `LogOnlyMessageDispatcher`
- [ ] 5. Create `shared/channel_dispatch/multi.py` — `MultiChannelMessageDispatcher` with per-dispatcher isolation
- [ ] 6. Create `shared/channel_dispatch/rate_limit.py` — `AsyncTokenBucket`
- [ ] 7. Create `shared/channel_dispatch/sign.py` — `hmac_sha256_hex` helper

## Layer 2 — Concrete adapters (shared/channel_dispatch/adapters/)

- [ ] 8. Create `shared/channel_dispatch/adapters/__init__.py` (empty)
- [ ] 9. Create `shared/channel_dispatch/adapters/telegram.py` — `TelegramBotMessageDispatcher` + `_HttpxTelegramTransport`
- [ ] 10. Create `shared/channel_dispatch/adapters/hermes.py` — `HermesWhatsAppMessageDispatcher` + `_HttpxHermesTransport`

## Layer 3 — Iguanatrader binding (contexts/approval/)

- [ ] 11. Add `build_outbound_message_from_request` + `resolve_recipients_from_request` + `_MessageDispatcherChannelAdapter` to `contexts/approval/dispatcher.py`
- [ ] 12. Add `_build_telegram_hermes_from_env(repository)` private helper
- [ ] 13. Extend `build_channel_dispatcher_from_env(repository=None)` with `telegram_hermes` kind + missing-credentials fallback
- [ ] 14. Wire daemon: pass `repository=ApprovalRepository()` to `build_channel_dispatcher_from_env(...)` in `cli/trading.py`

## Tests

- [ ] 15. `tests/unit/shared/channel_dispatch/test_log_only.py`
- [ ] 16. `tests/unit/shared/channel_dispatch/test_multi.py` — routing + isolation
- [ ] 17. `tests/unit/shared/channel_dispatch/test_telegram_adapter.py` — fake transport + rate-limiter acquire
- [ ] 18. `tests/unit/shared/channel_dispatch/test_hermes_adapter.py` — HMAC signature + filter
- [ ] 19. `tests/unit/shared/channel_dispatch/test_rate_limit.py` — timing-sensitive (use monotonic stub or accept ≥3.3s wall budget)
- [ ] 20. `tests/unit/shared/channel_dispatch/test_sign.py` — known-vector HMAC
- [ ] 21. `tests/property/test_channel_dispatch_isolation.py` — random good/bad recipients, no silent drops
- [ ] 22. `tests/integration/contexts/approval/test_channel_dispatcher_binding.py` — `authorized_senders` resolution + binding adapter

## Verification

- [ ] 23. `make ruff` + `make black-check` + `make mypy` locally green
- [ ] 24. `pytest apps/api/tests/unit/shared/channel_dispatch/ apps/api/tests/property/test_channel_dispatch_isolation.py apps/api/tests/integration/contexts/approval/test_channel_dispatcher_binding.py` green
- [ ] 25. Push branch + open PR + wait CI 14/14 green
- [ ] 26. Merge PR + archive openspec change to `openspec/changes/archive/2026-05-11-p1-channel-fanout-production/`
- [ ] 27. Fill `retros/p1-channel-fanout-production.md` with squash SHA + lines + CI rounds + pre-flag candidates
