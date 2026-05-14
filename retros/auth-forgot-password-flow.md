# Retrospective: auth-forgot-password-flow

- **PR**: [#135](https://github.com/Wizarck/iguanatrader/pull/135) (merged 2026-05-13, squash `ffcd21d`). Follow-up guardrail in [#137](https://github.com/Wizarck/iguanatrader/pull/137) (merged same day, squash `a078f06`, +406 lines) — refuse to rotate when no real channel is wired.
- **Archive path**: `openspec/changes/archive/2026-05-13-auth-forgot-password-flow/`
- **Lines shipped**: 1782 insertions / 4 deletions across 20 files (PR #135) + 406/2 (PR #137). CI green on first push for both.

## What worked

- **Anti-enumeration response shape** — `POST /forgot-password` always returns `200` + generic body whether the email is known or unknown. Operator-facing telemetry (`channel_dispatch.dispatched` + `auth.forgot_password.requested`) distinguishes the cases without leaking through the API. Standard practice; verified by the integration test that pins identical bytes across known/unknown branches.
- **`slowapi @limiter.limit("3/hour")` on the endpoint** — keyed by `(remote_ip, email)`; a single email tier is rate-limited independently per source IP. Protects both a known account (no spam) and an attacker's enumeration probes.
- **80-bit base32-no-confusables temp password generator** (`apps/api/src/iguanatrader/api/temp_password.py`) — alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (32 symbols, no `0/O/1/I/L`), formatted `XXXX-XXXX-XXXX-XXXX` for readability. Random source is `secrets.token_bytes`. Tested via property test (always 19 chars + only allowed alphabet).
- **Multi-channel dispatch via `build_user_channel_dispatcher_from_env`** — composition root resolves dispatcher = Email + Telegram + Hermes per env config + user's enabled channels. Reuses the slice P1 fanout core without conditional logic.
- **`telegram_chat_id` + `whatsapp_phone` columns on `User`** (migration `0014_user_recovery_channels.py`) — recovery channels are opt-in per user, set at admin-bootstrap or via future `/account/channels` page.
- **PR #137 guardrail** — after I locked myself out smoke-testing the endpoint with a LogOnly dispatcher (the temp password got logged but the body wasn't), I added a guardrail that recursively inspects `MultiChannelMessageDispatcher.inner` and refuses to rotate if no concrete deliverer is wired. The integration test pins this contract.

## What didn't

- **Smoke-test footgun** — I tested `/forgot-password` live in dev without verifying which dispatcher was configured. LogOnly only logs metadata (recipient + channel + outcome), NOT the message body — so the temp password was unrecoverable. Cost: ~10 min recovery via `iguanatrader admin bootstrap-tenant --force-reset` to a known password. **PR #137 fixes this for any future operator.** Pre-flag: never test rotation endpoints against a LogOnly dispatcher even in dev — the rotation has happened by the time the log line is written.
- **argon2-cffi import hang on Windows** during slice 3's hypothesis test run — environmental, not slice-specific. Linux CI was unaffected. Workaround was to skip the hanging property test locally + verify on CI; not a code-level fix. Pre-flag: when a CI-clean test hangs locally on Windows, suspect `argon2-cffi` or `cryptography` C-extension paths — don't burn time hunting it in slice code.
- **No "what email did we send to?" feedback in the UI** by design (anti-enumeration), but UX-wise users wonder if they typed the right email. Mitigated only by the rate-limit per-(IP,email) and the generic copy "if the email is registered, you'll receive a message". The trade-off (privacy > UX) is correct for a trading app.

## Carry-forward

- **WhatsApp adapter** — schema column `whatsapp_phone` exists but no adapter dispatches there yet. Would need a Twilio API + webhook adapter or similar; tactical follow-up.
- **Recovery-channel management UI at `/account/channels`** — currently `telegram_chat_id` + `whatsapp_phone` are set only at admin bootstrap. Self-service edit page is a 1-2h slice.
- **Audit log of password rotations** — `auth.forgot_password.rotated` event is logged but not surfaced. A `/account/security` page showing "last rotated YYYY-MM-DD via channel email" would help users notice unauthorized rotations.
- **Email + Telegram + Hermes all dispatch in fanout** — currently best-effort (one failure doesn't block the others). A future slice could add a "all-or-none" mode if the user has explicit preference.

## Pattern usage

- **Anti-enumeration via uniform 200 + generic body** — copy this shape for any future "is X registered?" endpoint (account-recovery, signup-duplicate-check, etc.).
- **`@limiter.limit("3/hour", key_func=...)` keyed by `(ip, email)`** — limit-per-pair, not limit-per-IP, prevents the obvious bypass.
- **Property tests for password generators** — `@pytest.mark.property` decorator + hypothesis strategy over `bytes` input → assertions about format + alphabet. Reuse for any future security-token generator.
- **Recursive dispatcher inspection for guardrails** — the `_dispatcher_can_deliver` helper unwraps `MultiChannelMessageDispatcher.inner` recursively; reuse for any "is this dispatcher real?" check at composition boundaries.
