"""EmailSMTPDispatcher — generic SMTP email adapter.

Wraps an injectable :class:`EmailTransport` (default: aiosmtplib wrapper that
performs STARTTLS + login + ``send_message`` per dispatch call). Provider-
agnostic by design — vanilla SMTP, not Resend/SES/Postmark. Honours a
conservative 10-msg/s default rate via :class:`AsyncTokenBucket`.

The transport contract is slightly wider than :class:`OutboundTransport`
because email envelopes carry more than ``(address, body)``: the adapter
needs to pass subject + an optional HTML alternative + the sender envelope.
The wider contract lives in this module (``EmailTransport`` Protocol) so
the generic ``shared.channel_dispatch.protocol`` stays minimal and the
upstream-extractability invariant is preserved.
"""

from __future__ import annotations

import socket
from collections.abc import Sequence
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

import aiosmtplib
import structlog

from iguanatrader.shared.channel_dispatch.protocol import RateLimiter
from iguanatrader.shared.channel_dispatch.rate_limit import AsyncTokenBucket
from iguanatrader.shared.channel_dispatch.types import (
    DispatchResult,
    OutboundMessage,
    Recipient,
)

log = structlog.get_logger("iguanatrader.shared.channel_dispatch.adapters.email_smtp")

#: Conservative baseline rate — vanilla SMTP servers commonly accept ~10/s
#: without tripping reputation throttles. Override per-deployment as needed.
EMAIL_DEFAULT_RATE_PER_SECOND: float = 10.0
EMAIL_CHANNEL: str = "email"
#: Default port: STARTTLS submission per RFC 6409.
EMAIL_DEFAULT_PORT: int = 587
#: Default From: address — operator overrides via env var.
EMAIL_DEFAULT_FROM_ADDRESS: str = "iguanatrader@palafitofood.com"
EMAIL_DEFAULT_FROM_NAME: str = "iguanatrader"
#: Subject prefix applied to every outbound email (operator brand mark).
EMAIL_SUBJECT_PREFIX: str = "[iguanatrader]"


@runtime_checkable
class EmailTransport(Protocol):
    """Wire-level email send.

    Wider than :class:`OutboundTransport` because the envelope needs subject +
    optional HTML alternative + sender identity. Returns the wire message id
    on success; may raise on transport error (caller translates into a failed
    :class:`DispatchResult`).
    """

    async def send(
        self,
        *,
        to_address: str,
        subject: str,
        text_body: str,
        html_body: str | None,
    ) -> str: ...


class _AioSmtpEmailTransport:
    """Default transport: aiosmtplib STARTTLS + login + ``send_message``."""

    def __init__(
        self,
        *,
        host: str,
        port: int = EMAIL_DEFAULT_PORT,
        username: str,
        password: str,
        from_address: str = EMAIL_DEFAULT_FROM_ADDRESS,
        from_name: str = EMAIL_DEFAULT_FROM_NAME,
        use_tls: bool = True,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._username = username
        self._password = password
        self._from_address = from_address
        self._from_name = from_name
        self._use_tls = bool(use_tls)
        self._timeout = float(timeout)

    def _build_message(
        self,
        *,
        to_address: str,
        subject: str,
        text_body: str,
        html_body: str | None,
    ) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = f"{self._from_name} <{self._from_address}>"
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.set_content(text_body)
        if html_body:
            msg.add_alternative(html_body, subtype="html")
        return msg

    async def send(
        self,
        *,
        to_address: str,
        subject: str,
        text_body: str,
        html_body: str | None,
    ) -> str:
        msg = self._build_message(
            to_address=to_address,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
        # ``aiosmtplib.send`` performs: connect → STARTTLS (if requested) → login
        # → DATA → quit. Returns ``(errors, response)``; we only need confirmation
        # that no exception was raised. Wire message id is the canonical
        # ``Message-ID`` header set by aiosmtplib when missing.
        await aiosmtplib.send(
            msg,
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            start_tls=self._use_tls,
            timeout=self._timeout,
        )
        message_id = str(msg.get("Message-ID") or "")
        # Strip RFC 5322 angle brackets for parity with Telegram + Hermes wire ids.
        return message_id.strip("<>")


class EmailSMTPDispatcher:
    """Concrete dispatcher for ``channel == 'email'`` recipients.

    Mirrors the shape of :class:`TelegramBotMessageDispatcher` +
    :class:`HermesWhatsAppMessageDispatcher`: filter recipients by channel,
    rate-limit via :class:`AsyncTokenBucket`, translate transport exceptions
    into failed :class:`DispatchResult` rows so per-recipient failures never
    escape the batch.

    Subject + HTML alt body travel via :class:`OutboundMessage`:

    * ``message.subject`` — when set, becomes the email subject (with the
      ``[iguanatrader]`` prefix). When unset, defaults to a generic
      ``[iguanatrader] notification`` so the wire envelope is always valid.
    * ``message.metadata['html_body']`` — when present, attached as the
      ``multipart/alternative`` HTML part. ``message.body`` is the plain-text
      fallback.
    """

    def __init__(
        self,
        *,
        host: str | None = None,
        port: int = EMAIL_DEFAULT_PORT,
        username: str | None = None,
        password: str | None = None,
        from_address: str = EMAIL_DEFAULT_FROM_ADDRESS,
        from_name: str = EMAIL_DEFAULT_FROM_NAME,
        use_tls: bool = True,
        transport: EmailTransport | None = None,
        rate_limit: RateLimiter | None = None,
    ) -> None:
        if transport is None:
            if host is None or username is None or password is None:
                raise ValueError("either transport or host + username + password must be provided")
            transport = _AioSmtpEmailTransport(
                host=host,
                port=port,
                username=username,
                password=password,
                from_address=from_address,
                from_name=from_name,
                use_tls=use_tls,
            )
        self._transport: EmailTransport = transport
        self._rate_limit: RateLimiter = rate_limit or AsyncTokenBucket(
            rate_per_second=EMAIL_DEFAULT_RATE_PER_SECOND
        )

    def _build_subject(self, message: OutboundMessage) -> str:
        raw = (message.subject or "notification").strip() or "notification"
        if raw.startswith(EMAIL_SUBJECT_PREFIX):
            return raw
        return f"{EMAIL_SUBJECT_PREFIX} {raw}"

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        subject = self._build_subject(message)
        html_body = message.metadata.get("html_body") if message.metadata else None
        results: list[DispatchResult] = []
        for r in recipients:
            if r.channel != EMAIL_CHANNEL:
                results.append(
                    DispatchResult(
                        channel=r.channel,
                        address=r.address,
                        status="skipped",
                        wire_message_id=None,
                        error=f"email dispatcher cannot handle channel={r.channel!r}",
                    )
                )
                continue
            await self._rate_limit.acquire()
            try:
                wire_id = await self._transport.send(
                    to_address=r.address,
                    subject=subject,
                    text_body=message.body,
                    html_body=html_body,
                )
            except (aiosmtplib.SMTPException, socket.gaierror, TimeoutError) as exc:
                log.warning(
                    "channel_dispatch.email.send_failed",
                    address=r.address,
                    correlation_id=message.correlation_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                results.append(
                    DispatchResult(
                        channel=r.channel,
                        address=r.address,
                        status="failed",
                        wire_message_id=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            except Exception as exc:
                log.warning(
                    "channel_dispatch.email.send_failed_unexpected",
                    address=r.address,
                    correlation_id=message.correlation_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                results.append(
                    DispatchResult(
                        channel=r.channel,
                        address=r.address,
                        status="failed",
                        wire_message_id=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            results.append(
                DispatchResult(
                    channel=r.channel,
                    address=r.address,
                    status="delivered",
                    wire_message_id=wire_id,
                    error=None,
                )
            )
        return results


__all__ = [
    "EMAIL_CHANNEL",
    "EMAIL_DEFAULT_FROM_ADDRESS",
    "EMAIL_DEFAULT_FROM_NAME",
    "EMAIL_DEFAULT_PORT",
    "EMAIL_DEFAULT_RATE_PER_SECOND",
    "EMAIL_SUBJECT_PREFIX",
    "EmailSMTPDispatcher",
    "EmailTransport",
]
