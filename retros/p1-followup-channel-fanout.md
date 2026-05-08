# Retrospective: p1-followup-channel-fanout

> **Forward-authored**. Minimum-viable channel-fanout abstraction.

- **PR**: TBD
- **Archive path**: `openspec/changes/archive/<archive-date>-p1-followup-channel-fanout/`
- **Lines shipped**: ~250 LoC (~110 src + ~140 tests + ~50 retro/openspec).

## What worked

- _(fill on archive — pre-flag candidates: 6th canonical bus-bridge follow-up + 3rd Protocol+InTreeFake+DeferredProductionInstall (LogOnly is the InTree fake; production telegram_hermes deferred). Backwards-compat optional kwarg on `ApprovalService.__init__` (P1 + P1-followup archive callers leave it None implicitly via default). FR32 isolation enforced via try/except in `_approval_requested_handler` — bad dispatcher cannot break the audit-write path.)_

## What didn't

- _(fill on archive — pre-flag candidates: production push (real Telegram bot send + Hermes WhatsApp HTTP) deferred — operator can dashboard-SSE-click-to-approve in the meantime. Channel push will require: per-tenant chat_id table, Telegram bot token in SOPS bundle, Hermes HTTP credentials, rate-limit (Telegram bot API has 30 messages/sec), HMAC payload signing for Hermes. Listed for a future `p1-channel-fanout-production` operator slice.)_

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
