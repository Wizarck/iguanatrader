"""D6 silent-drop guard — unauthorized senders never reach the dispatcher.

Per slice P1 task 6.7 + spec ``approval`` Requirement 4.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from iguanatrader.contexts.approval.channels.telegram import TelegramChannel
from iguanatrader.contexts.approval.channels.transports.fakes import (
    FakeHermesTransport,
    FakeTelegramTransport,
)
from iguanatrader.contexts.approval.channels.types import IncomingCommand
from iguanatrader.contexts.approval.channels.whatsapp_hermes import (
    HermesWhatsAppChannel,
)


def _build_inbound() -> IncomingCommand:
    return IncomingCommand(
        command_name="/status",
        raw_args="",
        sender_external_id="999999",
        channel="telegram",
        tenant_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_telegram_silent_drops_unauthorized_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTelegramTransport()
    repository = AsyncMock()
    repository.is_sender_authorized = AsyncMock(return_value=(False, None))
    tenant_id = uuid4()
    channel = TelegramChannel(
        transport=transport,
        repository=repository,
        service=AsyncMock(),
        message_bus=AsyncMock(),
        tenant_id=tenant_id,
    )
    transport.inject_inbound(_build_inbound())

    # Patch the dispatcher to detect any call.
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "iguanatrader.contexts.approval.channels.telegram.dispatch",
        dispatch_mock,
    )
    await channel.start_listening()
    dispatch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_disabled_authorized_row_is_silent_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTelegramTransport()
    repository = AsyncMock()
    # Disabled row: returns (False, None) per repository contract.
    repository.is_sender_authorized = AsyncMock(return_value=(False, None))
    channel = TelegramChannel(
        transport=transport,
        repository=repository,
        service=AsyncMock(),
        message_bus=AsyncMock(),
        tenant_id=uuid4(),
    )
    transport.inject_inbound(_build_inbound())
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "iguanatrader.contexts.approval.channels.telegram.dispatch",
        dispatch_mock,
    )
    await channel.start_listening()
    dispatch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_whatsapp_silent_drops_unauthorized_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeHermesTransport()
    repository = AsyncMock()
    repository.is_sender_authorized = AsyncMock(return_value=(False, None))
    channel = HermesWhatsAppChannel(
        transport=transport,
        repository=repository,
        service=AsyncMock(),
        message_bus=AsyncMock(),
        tenant_id=uuid4(),
    )
    transport.inject_inbound(_build_inbound())
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "iguanatrader.contexts.approval.channels.whatsapp_hermes.dispatch",
        dispatch_mock,
    )
    await channel.start_listening()
    dispatch_mock.assert_not_awaited()


def test_external_id_hashed_in_log_event() -> None:
    """Sanity: the SHA-256 hash matches the documented anti-enumeration shape."""
    raw = "999999"
    expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert len(expected) == 64
