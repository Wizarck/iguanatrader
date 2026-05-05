"""Hermes / WhatsApp channel resilience — heartbeat + canonical backoff.

Per slice P1 task 6.2 + spec ``approval`` Requirement 2 + FR37
invariant. Same shape as ``test_telegram_resilience.py`` — proves
NFR-I6 reconnect contract is identical to Telegram.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from iguanatrader.contexts.approval.channels.transports.fakes import (
    FakeHermesTransport,
)
from iguanatrader.contexts.approval.channels.whatsapp_hermes import (
    HermesWhatsAppChannel,
)
from iguanatrader.shared.heartbeat import ConnectionState


@pytest.mark.asyncio
async def test_hermes_reconnect_walks_canonical_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeHermesTransport()
    transport.simulate_health_failure(5)
    channel = HermesWhatsAppChannel(
        transport=transport,
        repository=AsyncMock(),
        service=AsyncMock(),
        message_bus=AsyncMock(),
        tenant_id=uuid4(),
    )
    channel.mark_connected()
    await channel.mark_disconnected()
    sleeps: list[float] = []

    async def _capture_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(
        "iguanatrader.shared.heartbeat.asyncio.sleep",
        _capture_sleep,
    )
    await channel.reconnect_loop()
    assert channel.state is ConnectionState.CONNECTED
    assert len(sleeps) == 5
    bases = [3.0, 6.0, 12.0, 24.0, 48.0]
    for actual, base in zip(sleeps, bases, strict=True):
        assert base * 0.8 <= actual <= base * 1.2, (actual, base)


@pytest.mark.asyncio
async def test_hermes_on_disconnect_fires_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeHermesTransport()
    channel = HermesWhatsAppChannel(
        transport=transport,
        repository=AsyncMock(),
        service=AsyncMock(),
        message_bus=AsyncMock(),
        tenant_id=uuid4(),
    )
    count = 0

    async def _on_disc() -> None:
        nonlocal count
        count += 1

    monkeypatch.setattr(channel, "_on_disconnect", _on_disc)
    channel.mark_connected()
    await channel.mark_disconnected()
    await channel.mark_disconnected()
    assert count == 1
