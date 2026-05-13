"""Unit tests for :class:`EmailSMTPDispatcher` (slice channel-email-adapter)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import aiosmtplib
import pytest
from iguanatrader.shared.channel_dispatch import (
    AsyncTokenBucket,
    OutboundMessage,
    Recipient,
)
from iguanatrader.shared.channel_dispatch.adapters.email_smtp import (
    EMAIL_CHANNEL,
    EMAIL_SUBJECT_PREFIX,
    EmailSMTPDispatcher,
    _AioSmtpEmailTransport,
)


class _FakeEmailTransport:
    """Records send calls; returns deterministic wire id."""

    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail_on = fail_on or set()

    async def send(
        self,
        *,
        to_address: str,
        subject: str,
        text_body: str,
        html_body: str | None,
    ) -> str:
        self.calls.append(
            {
                "to_address": to_address,
                "subject": subject,
                "text_body": text_body,
                "html_body": html_body,
            }
        )
        if to_address in self._fail_on:
            raise RuntimeError(f"forced failure for {to_address}")
        return f"email-{to_address}"


def _make_message(
    *,
    subject: str | None = "Approve trade",
    html_body: str | None = "<p>approve?</p>",
) -> OutboundMessage:
    metadata: dict[str, str] = {}
    if html_body is not None:
        metadata["html_body"] = html_body
    return OutboundMessage(
        body="approve?",
        correlation_id="corr-1",
        metadata=metadata,
        subject=subject,
    )


def test_constructor_requires_transport_or_host_username_password() -> None:
    with pytest.raises(ValueError):
        EmailSMTPDispatcher()
    with pytest.raises(ValueError):
        EmailSMTPDispatcher(host="smtp.test")  # missing username + password
    with pytest.raises(ValueError):
        EmailSMTPDispatcher(host="smtp.test", username="u")  # missing password


@pytest.mark.asyncio
async def test_delivers_with_correct_envelope() -> None:
    """Happy path: transport called once per recipient with correct envelope."""
    transport = _FakeEmailTransport()
    dispatcher = EmailSMTPDispatcher(
        transport=transport,
        rate_limit=AsyncTokenBucket(rate_per_second=1000.0, burst=10),
    )
    recipients = [
        Recipient(channel=EMAIL_CHANNEL, address="alice@example.com"),
        Recipient(channel=EMAIL_CHANNEL, address="bob@example.com"),
    ]
    results = await dispatcher.dispatch(message=_make_message(), recipients=recipients)

    assert [r.status for r in results] == ["delivered", "delivered"]
    assert [r.wire_message_id for r in results] == [
        "email-alice@example.com",
        "email-bob@example.com",
    ]
    assert len(transport.calls) == 2
    first = transport.calls[0]
    assert first["to_address"] == "alice@example.com"
    assert first["subject"] == f"{EMAIL_SUBJECT_PREFIX} Approve trade"
    assert first["text_body"] == "approve?"
    assert first["html_body"] == "<p>approve?</p>"


@pytest.mark.asyncio
async def test_rate_limiter_throttles_burst() -> None:
    """11th call against a 10/s bucket waits ~1s for the next token."""
    transport = _FakeEmailTransport()
    # burst=10 (matches the default ceiling at rate=10) → 11 calls cross
    # the refill boundary at least once.
    bucket = AsyncTokenBucket(rate_per_second=10.0, burst=10)
    dispatcher = EmailSMTPDispatcher(transport=transport, rate_limit=bucket)
    recipients = [
        Recipient(channel=EMAIL_CHANNEL, address=f"user{i}@example.com") for i in range(11)
    ]
    start = time.monotonic()
    results = await dispatcher.dispatch(message=_make_message(), recipients=recipients)
    elapsed = time.monotonic() - start

    assert all(r.status == "delivered" for r in results)
    assert len(transport.calls) == 11
    # 10 instant + 1 waits ~0.1s (1/rate). The proposal language says ">=1s"
    # but that's a typo from the legacy Hermes proposal: the canonical
    # ``rate=10/s, burst=10`` bucket only needs to wait ``1/rate=0.1s`` for
    # the 11th token. Assert the meaningful invariant: the 11th call DID
    # block (elapsed > 0) rather than fly straight through.
    assert elapsed >= 0.09


@pytest.mark.asyncio
async def test_skips_non_email_recipients() -> None:
    """Channel filter: non-email recipients return skipped + no transport call."""
    transport = _FakeEmailTransport()
    dispatcher = EmailSMTPDispatcher(
        transport=transport,
        rate_limit=AsyncTokenBucket(rate_per_second=1000.0, burst=10),
    )
    recipients = [
        Recipient(channel="telegram", address="111"),
        Recipient(channel="whatsapp", address="+34999"),
        Recipient(channel=EMAIL_CHANNEL, address="alice@example.com"),
    ]
    results = await dispatcher.dispatch(message=_make_message(), recipients=recipients)

    assert results[0].status == "skipped"
    assert results[0].error is not None and "channel='telegram'" in results[0].error
    assert results[1].status == "skipped"
    assert results[1].error is not None and "channel='whatsapp'" in results[1].error
    assert results[2].status == "delivered"
    # Only the email recipient hit the transport.
    assert len(transport.calls) == 1
    assert transport.calls[0]["to_address"] == "alice@example.com"


@pytest.mark.asyncio
async def test_default_transport_uses_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default :class:`_AioSmtpEmailTransport` calls aiosmtplib.send with
    ``start_tls=True`` (STARTTLS submission). Patches the module-level
    ``aiosmtplib.send`` so no socket is opened."""
    captured: dict[str, Any] = {}

    async def _fake_send(msg: Any, **kwargs: Any) -> tuple[dict[str, Any], str]:
        captured["msg"] = msg
        captured["kwargs"] = kwargs
        return ({}, "250 OK")

    monkeypatch.setattr(aiosmtplib, "send", _fake_send)
    transport = _AioSmtpEmailTransport(
        host="smtp.example.com",
        port=587,
        username="user",
        password="pass",
        from_address="iguanatrader@palafitofood.com",
        from_name="iguanatrader",
        use_tls=True,
    )
    wire_id = await transport.send(
        to_address="alice@example.com",
        subject="[iguanatrader] hi",
        text_body="hi there",
        html_body="<p>hi there</p>",
    )

    kwargs = captured["kwargs"]
    assert kwargs["hostname"] == "smtp.example.com"
    assert kwargs["port"] == 587
    assert kwargs["username"] == "user"
    assert kwargs["password"] == "pass"
    assert kwargs["start_tls"] is True
    msg = captured["msg"]
    assert msg["From"] == "iguanatrader <iguanatrader@palafitofood.com>"
    assert msg["To"] == "alice@example.com"
    assert msg["Subject"] == "[iguanatrader] hi"
    # ``wire_id`` is the Message-ID stripped of angle brackets when present;
    # the fake send doesn't add one, so the EmailMessage carries no Message-ID
    # and the helper returns the empty string. That is acceptable — the
    # invariant is the dispatcher loops back a string (no exception).
    assert isinstance(wire_id, str)


@pytest.mark.asyncio
async def test_transport_failure_captured_as_failed_result() -> None:
    """Transport raises → ``DispatchResult.status='failed'`` + error captured."""
    transport = _FakeEmailTransport(fail_on={"alice@example.com"})
    dispatcher = EmailSMTPDispatcher(
        transport=transport,
        rate_limit=AsyncTokenBucket(rate_per_second=1000.0, burst=10),
    )
    recipients = [
        Recipient(channel=EMAIL_CHANNEL, address="alice@example.com"),
        Recipient(channel=EMAIL_CHANNEL, address="bob@example.com"),
    ]
    results = await dispatcher.dispatch(message=_make_message(), recipients=recipients)

    assert results[0].status == "failed"
    assert results[0].error is not None
    assert "forced failure" in results[0].error
    assert results[0].wire_message_id is None
    # Per FR32 isolation: the second recipient is unaffected.
    assert results[1].status == "delivered"


@pytest.mark.asyncio
async def test_handles_smtp_specific_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """``aiosmtplib.SMTPException`` is captured into a failed
    :class:`DispatchResult` rather than escaping."""

    async def _raise_smtp(msg: Any, **kwargs: Any) -> tuple[dict[str, Any], str]:
        raise aiosmtplib.SMTPException("smtp 421 service unavailable")

    monkeypatch.setattr(aiosmtplib, "send", _raise_smtp)
    dispatcher = EmailSMTPDispatcher(
        host="smtp.example.com",
        username="u",
        password="p",
        rate_limit=AsyncTokenBucket(rate_per_second=1000.0, burst=10),
    )
    # Sanity: confirm we hit the asyncio path via the dispatcher.
    results = await asyncio.wait_for(
        dispatcher.dispatch(
            message=_make_message(),
            recipients=[Recipient(channel=EMAIL_CHANNEL, address="alice@example.com")],
        ),
        timeout=5.0,
    )
    assert results[0].status == "failed"
    assert results[0].error is not None and "SMTPException" in results[0].error


def test_subject_prefix_is_idempotent() -> None:
    """A subject already starting with the brand prefix is not doubled."""
    transport = _FakeEmailTransport()
    dispatcher = EmailSMTPDispatcher(transport=transport)
    assert dispatcher._build_subject(_make_message(subject="[iguanatrader] hello")) == (
        "[iguanatrader] hello"
    )
    assert dispatcher._build_subject(_make_message(subject="hello")) == "[iguanatrader] hello"
    assert dispatcher._build_subject(_make_message(subject=None)) == "[iguanatrader] notification"
