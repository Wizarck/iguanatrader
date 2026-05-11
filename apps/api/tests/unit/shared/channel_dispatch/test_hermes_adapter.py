"""Unit tests for :class:`HermesWhatsAppMessageDispatcher`."""

from __future__ import annotations

import pytest
from iguanatrader.shared.channel_dispatch import (
    AsyncTokenBucket,
    OutboundMessage,
    Recipient,
)
from iguanatrader.shared.channel_dispatch.adapters.hermes import (
    WHATSAPP_CHANNEL,
    HermesWhatsAppMessageDispatcher,
)


class _FakeHermesTransport:
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail_on = fail_on or set()

    async def send(self, *, address: str, body: str) -> str:
        self.calls.append((address, body))
        if address in self._fail_on:
            raise RuntimeError(f"forced failure for {address}")
        return f"wa-{address}"


def _make_message() -> OutboundMessage:
    return OutboundMessage(body="approve?", correlation_id="corr-1")


def test_constructor_requires_transport_or_base_url_plus_secret() -> None:
    with pytest.raises(ValueError):
        HermesWhatsAppMessageDispatcher()
    with pytest.raises(ValueError):
        HermesWhatsAppMessageDispatcher(base_url="http://hermes")  # missing secret


@pytest.mark.asyncio
async def test_delivers_to_whatsapp_recipients() -> None:
    transport = _FakeHermesTransport()
    dispatcher = HermesWhatsAppMessageDispatcher(
        transport=transport,
        rate_limit=AsyncTokenBucket(rate_per_second=1000.0, burst=10),
    )
    recipients = [
        Recipient(channel=WHATSAPP_CHANNEL, address="+34111"),
        Recipient(channel=WHATSAPP_CHANNEL, address="+34222"),
    ]
    results = await dispatcher.dispatch(message=_make_message(), recipients=recipients)
    assert len(results) == 2
    assert all(r.status == "delivered" for r in results)
    assert [r.wire_message_id for r in results] == ["wa-+34111", "wa-+34222"]


@pytest.mark.asyncio
async def test_skips_non_whatsapp_recipients() -> None:
    transport = _FakeHermesTransport()
    dispatcher = HermesWhatsAppMessageDispatcher(
        transport=transport,
        rate_limit=AsyncTokenBucket(rate_per_second=1000.0, burst=10),
    )
    recipients = [
        Recipient(channel="telegram", address="111"),
        Recipient(channel=WHATSAPP_CHANNEL, address="+34222"),
    ]
    results = await dispatcher.dispatch(message=_make_message(), recipients=recipients)
    assert results[0].status == "skipped"
    assert results[1].status == "delivered"
    assert transport.calls == [("+34222", "approve?")]


@pytest.mark.asyncio
async def test_isolates_failing_recipient() -> None:
    transport = _FakeHermesTransport(fail_on={"+34111"})
    dispatcher = HermesWhatsAppMessageDispatcher(
        transport=transport,
        rate_limit=AsyncTokenBucket(rate_per_second=1000.0, burst=10),
    )
    recipients = [
        Recipient(channel=WHATSAPP_CHANNEL, address="+34111"),
        Recipient(channel=WHATSAPP_CHANNEL, address="+34222"),
    ]
    results = await dispatcher.dispatch(message=_make_message(), recipients=recipients)
    assert results[0].status == "failed"
    assert results[0].error is not None
    assert results[1].status == "delivered"


@pytest.mark.asyncio
async def test_httpx_transport_signs_canonical_body() -> None:
    """Verify the default httpx transport posts a canonically-serialized body
    with the matching X-Signature header (via injected stub client)."""
    import json
    from typing import Any

    import httpx
    from iguanatrader.shared.channel_dispatch import hmac_sha256_hex
    from iguanatrader.shared.channel_dispatch.adapters.hermes import _HttpxHermesTransport

    captured: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, json={"message_id": "wa-xyz"})

    secret = b"shh"
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        transport = _HttpxHermesTransport(
            base_url="http://hermes.test",
            hmac_secret=secret,
            client=client,
        )
        wire_id = await transport.send(address="+34111", body="hello")

    assert wire_id == "wa-xyz"
    assert captured["url"] == "http://hermes.test/messages"
    expected_payload = json.dumps(
        {"recipient": "+34111", "body": "hello"}, separators=(",", ":")
    ).encode("utf-8")
    assert captured["body"] == expected_payload
    expected_sig = f"sha256={hmac_sha256_hex(secret, expected_payload)}"
    assert captured["headers"]["x-signature"] == expected_sig
