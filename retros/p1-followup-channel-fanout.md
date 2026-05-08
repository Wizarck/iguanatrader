# Retrospective: p1-followup-channel-fanout

> **Forward-authored**. Minimum-viable channel-fanout abstraction.

- **PR**: [#111](https://github.com/Wizarck/iguanatrader/pull/111) (merged 2026-05-08, squash `17b56d5`).
- **Archive path**: `openspec/changes/archive/2026-05-08-p1-followup-channel-fanout/`
- **Lines shipped**: 411 insertions across 7 files. CI 14/14 verde tras 1 fix round (round 1: SimpleNamespace test fixture failed mypy --strict against ApprovalRequestRow Protocol type + trailing whitespace in proposal.md caught by pre-commit).

## What worked

- 6th canonical bus-bridge follow-up + 3rd Protocol+InTreeFake+DeferredProductionInstall (LogOnly = InTree fake; production telegram_hermes deferred).
- Backwards-compat optional kwarg on `ApprovalService.__init__` (P1 + P1-followup archive callers leave it None implicitly via default).
- FR32 isolation enforced via try/except in `_approval_requested_handler` — bad dispatcher cannot break the audit-write path.
- Composition root `build_channel_dispatcher_from_env()` matches the same pattern from R6's `build_hindsight_adapter_from_env()` (env-driven kind selection with InTree fake fallback).

## What didn't

- Test fixture used `SimpleNamespace` where Protocol expected `ApprovalRequestRow`; mypy --strict caught it. Fix: build real `ApprovalRequestRow` instances via a `_make_request_row` helper. Pre-flag for future tests touching Protocol-typed adapters.
- Trailing whitespace in `proposal.md` caught by pre-commit `trim-trailing-whitespace` hook. Trivial fix; can be prevented by running pre-commit locally before push.
- Production push (real Telegram bot send + Hermes WhatsApp HTTP) deferred — operator can dashboard-SSE-click-to-approve in the meantime. Channel push will require: per-tenant chat_id table, Telegram bot token in SOPS bundle, Hermes HTTP credentials, rate-limit (Telegram bot API has 30 messages/sec), HMAC payload signing for Hermes. Listed for a future `p1-channel-fanout-production` operator slice.

## Carry-forward

- **`p1-channel-fanout-production` slice** (future operator work):
  - `TelegramBotChannelDispatcher` — Telegram bot send via existing `TelegramChannel` (P1 archive).
  - `HermesWhatsAppChannelDispatcher` — Hermes HTTP send via existing `HermesWhatsAppChannel`.
  - `MultiChannelDispatcher` — composite that fans out per `request.delivered_to_channels`.
  - Per-tenant `chat_id` + `phone_number` lookup (probably extend `authorized_senders` table).
  - SOPS bundles for credentials.
  - Rate-limit guards.
- **MVP v1.0 + v1 backlog**: 6 of 7 backlog items closed (this slice is the 6th); the 7th (`p1-channel-fanout-production`) is a deliberate ops-config-blocked deferral.

## Pattern usage

- **Bus-bridge follow-up #6**: K1-followup + P1-followup + T4-followup-market-data internal + R6 + this. Sixth confirmed instance.
- **Protocol+InTreeFake+DeferredProductionInstall #3**: ChannelDispatcher Protocol + LogOnlyChannelDispatcher (InTree fake) + future telegram_hermes (DeferredProductionInstall).
