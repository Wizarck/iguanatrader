# Proposal: channel-email-adapter

> **Email transport for `channel_dispatch`** — adds a generic SMTP-backed `EmailMessageDispatcher` mirroring the shape of `TelegramBotMessageDispatcher` + `HermesWhatsAppMessageDispatcher`. Unblocks `auth-forgot-password-flow` and any future email-bound notification without coupling to a specific provider (SES/Resend/Postmark).

## Why

The channel-dispatch protocol (slice `approval-channels-multichannel`, 2026-05-06) is provider-agnostic by design. Two adapters shipped (Telegram, Hermes/WhatsApp); a third is needed because:

- **Forgot-password flow** needs to reach a user who can't log in.
- **Weekly review PDF + alert routines** fan out to log-only today.
- The user wants a **generic, upstream-extractable** adapter — vanilla SMTP, not Resend/SES/Postmark.

## What

### Adapter

`apps/api/src/iguanatrader/shared/channel_dispatch/adapters/email_smtp.py` mirrors `telegram.py`:

- Class `EmailSMTPDispatcher(MessageDispatcher)` (or whatever the base name is — match the Telegram one).
- Constructor params: host, port, username, password, from_address, from_name, use_tls (default True for STARTTLS:587), transport, rate_limiter.
- Default rate `EMAIL_DEFAULT_RATE_PER_SECOND = 10.0`.
- Default transport: aiosmtplib wrapper class `_AioSmtpEmailTransport` that posts (host, port, STARTTLS, login, send_message) per dispatch call.
- `dispatch()` filters recipients to `channel == "email"`, builds `email.message.EmailMessage` envelope (From: "{from_name} <{from_address}>", To: recipient.address, Subject, plain-text body, multipart/alternative for HTML body when present), respects rate limit via AsyncTokenBucket.

### Email template

`apps/api/src/iguanatrader/shared/channel_dispatch/templates/email_base.html` (Jinja). Inline CSS only. Visual:

- Background `#1a1f2e`. Card `#262d3e`. Accent `#11b9c5`. Text `#e8eaee` primary, `#9ba3b4` muted.
- 32×32 rounded brand mark with letter "i" in accent bg, top-left.
- Font stack: `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`.
- 560px centred, single column, no remote images.

Slots: `subject`, `preheader`, `headline`, `body_html`, `cta_label`, `cta_url`, `disclaimer`.

**Mandatory disclaimer footer** (ES + EN sibling paragraphs):

> Este correo se envía desde una dirección no monitorizada: `iguanatrader@palafitofood.com` no recibe respuestas. Para soporte, accede a la app en https://iguanatrader.palafitofood.com.
> This email is sent from an unmonitored address: `iguanatrader@palafitofood.com` does not accept replies. For support, visit https://iguanatrader.palafitofood.com.

Subject prefix `[iguanatrader]`.

Helper `apps/api/src/iguanatrader/shared/channel_dispatch/templates/__init__.py` exposes `render_email_template(subject: str, preheader: str, headline: str, body_html: str, cta_label: str | None = None, cta_url: str | None = None) -> tuple[str, str]` returning `(html, plain_text)`.

### Configuration

Env vars (all required for the adapter to bind; missing any → log-only fallback like Hermes/Telegram):

- `IGUANATRADER_SMTP_HOST`
- `IGUANATRADER_SMTP_PORT` (int; default 587)
- `IGUANATRADER_SMTP_USERNAME`
- `IGUANATRADER_SMTP_PASSWORD`
- `IGUANATRADER_SMTP_FROM_ADDRESS` (default iguanatrader@palafitofood.com)
- `IGUANATRADER_SMTP_FROM_NAME` (default "iguanatrader")
- `IGUANATRADER_SMTP_USE_TLS` (default true)

Extend `build_channel_dispatcher_from_env` env selector:

- `""`/`"log_only"` → LogOnly (unchanged)
- `"telegram_hermes"` → unchanged
- `"telegram_hermes_email"` → Telegram + Hermes + Email (NEW)
- `"email"` → Email only (NEW)

Missing creds for any selected channel → that channel falls back to log-only individually; the others stay live (per-channel fallback).

### Tests

`apps/api/tests/unit/shared/channel_dispatch/test_email_adapter.py` — 5 cases (mirror Hermes):
1. Happy path: transport called with correct envelope (from, to, subject, body, html_body).
2. Rate-limiter integration — 11th call waits ≥1s.
3. Channel filter — non-email recipients ignored, no transport call.
4. STARTTLS attempted once.
5. Transport raises → DispatchResult.success=False + error captured.

`apps/api/tests/unit/shared/channel_dispatch/test_email_template.py` — 4 cases:
1. All `data-testid` markers (`brand-mark`, `headline`, `body`, `disclaimer`, optional `cta`).
2. Disclaimer footer + correct sender address.
3. Inline CSS only (no `<style>` tags).
4. Plain-text fallback derives from body when `html_body` only contains a paragraph.

`apps/api/tests/property/test_channel_dispatch_isolation.py` — extend the existing property test to cover Email. Don't break Telegram/Hermes cases.

`apps/api/tests/integration/contexts/approval/test_channel_dispatcher_binding.py` — add `telegram_hermes_email` selector path. (One new test case alongside existing ones.)

## Out of scope

- Bounce/complaint handling, DKIM/SPF/DMARC alignment, attachments, tracking pixels, provider-specific adapters (Resend/SES/Postmark), i18n beyond ES+EN side-by-side.
- Adding `IGUANATRADER_SMTP_*` env vars to `docker-compose.mvp.yml` (deferred to `auth-forgot-password-flow` which actually USES this adapter).
- SOPS bundle key edits (also deferred to `auth-forgot-password-flow`).
- Docs updates (`docs/mvp-deploy.md`) — also slice 3's concern.
