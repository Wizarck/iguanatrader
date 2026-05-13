# Retrospective: channel-email-adapter

- **PR**: [#131](https://github.com/Wizarck/iguanatrader/pull/131) (merged 2026-05-13, squash `9a16984`).
- **Archive path**: `openspec/changes/archive/2026-05-13-channel-email-adapter/`
- **Lines shipped**: 1307 insertions / 53 deletions across 14 files. CI green on first push.

## What worked

- **Activating the dormant `EmailSMTPDispatcher` via the existing `MessageDispatcher` protocol** — zero changes to `MultiChannelMessageDispatcher` or the dispatcher composition. The slice P1 fanout core was correctly designed for upstream extraction; email plugged in as a peer of Telegram + Hermes without protocol edits.
- **Jinja2 inline-CSS email template** (`templates/email_base.html` + `render_email_template`) renders identically across Gmail web, Outlook desktop, Apple Mail. Inline CSS is unavoidable for Outlook compatibility — the upfront ugliness pays for itself on first cross-client test.
- **`aiosmtplib` for async SMTP transport** keeps the dispatcher non-blocking; the existing structlog instrumentation surfaces SMTP failures via the same `channel_dispatch.failed` event as Telegram/Hermes.
- **`build_channel_dispatcher_from_env` selector extended with `email` and `telegram_hermes_email`** — the composition root choice stays declarative + env-driven. No special-casing of email in callsites.
- **Branded look&feel (OKLCH dark palette matching the webapp)** + ES disclaimer "no recibimos correos" — keeps the email visually consistent with the app even though replies are bounced.

## What didn't

- **Missing test for charset on non-ASCII bodies** caught only by mypy strict + reviewer-style local pass. Body bytes were `str.encode("ascii")` initially; I rewrote to `encode("utf-8")` + explicit `Content-Type: text/html; charset=utf-8` header. The 5min cost would have been zero if I'd defaulted to utf-8 from the start. Pre-flag: when serialising any user-visible body to bytes, default to utf-8 explicitly — never `str.encode()` (uses ASCII by default in stdlib `email` module helpers).
- **Initial `_AioSmtpEmailTransport` swallowed `SMTPResponseException` from auth failures** as a generic `DispatchError`, hiding the 535 (bad credentials) from operators. Fixed in-slice by adding an `SMTPAuthenticationError` → `DispatchAuthError` mapping path. Pre-flag: when wrapping a third-party library that exposes typed exceptions, mirror the type taxonomy on the way out — don't collapse to a single error type.

## Carry-forward

- **DKIM signing** — currently the SMTP relay (e.g., Postfix on the VPS) is expected to sign outgoing mail. A future slice could add `dkimpy` for app-layer signing if the operator runs without a relay.
- **Email throttling per-tenant** — `slowapi`-style rate limit on `EmailSMTPDispatcher.send`; not load-bearing for MVP volume but a 1-tenant brute-force could hammer the relay.
- **Provider abstraction** (Mailgun / SES / Postmark) — the `_AioSmtpEmailTransport` Protocol is upstream-extractable; alternative providers are a tactical follow-up if relay availability becomes an issue.
- **HTML→text fallback (`text/plain` multipart sibling)** — current emails are `text/html` only; spam filters score multipart higher. Tactical follow-up.

## Pattern usage

- **Adapter Protocol + composition-root selector** — every channel adapter (Telegram, Hermes, Email) is one file in `shared/channel_dispatch/adapters/` + one selector in `contexts/approval/dispatcher.py`. New channels (Discord, SMS, push) drop into the same shape.
- **Jinja2 + inline CSS for transactional email** — the `render_email_template` helper is the single entrypoint; future emails (welcome, password reset, daily digest) reuse the wrapper + override the inner body block.
- **`structlog.bind(channel="email")` per-adapter context** — every dispatcher carries its channel name into the log line, so the operator can filter `channel_dispatch.dispatched channel=email` cleanly.
