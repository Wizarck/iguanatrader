"""Telegram channel resilience — heartbeat + canonical backoff.

Per slice P1 task 6.1 + spec ``approval`` Requirement 2.

The test drives :class:`HeartbeatMixin.reconnect_loop` against a
:class:`FakeTelegramTransport` configured to fail the first 3 health
checks then recover. We assert:

* The reconnect_loop walks attempts 0..3 with the canonical backoff
  ``[3, 6, 12]`` seconds (jitter = ±20%) — captured by patching
  :func:`asyncio.sleep`.
* ``_on_disconnect`` fires exactly once across the entire flow.
* The channel ends in :class:`ConnectionState.CONNECTED`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from iguanatrader.contexts.approval.channels.telegram import TelegramChannel
from iguanatrader.contexts.approval.channels.transports.fakes import (
    FakeTelegramTransport,
)
from iguanatrader.shared.heartbeat import ConnectionState


@pytest.mark.asyncio
async def test_telegram_reconnect_walks_canonical_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTelegramTransport()
    transport.simulate_health_failure(3)
    channel = TelegramChannel(
        transport=transport,
        repository=AsyncMock(),
        service=AsyncMock(),
        message_bus=AsyncMock(),
        tenant_id=uuid4(),
    )
    channel.mark_connected()
    await channel.mark_disconnected()
    assert channel.state is ConnectionState.DISCONNECTED

    sleeps: list[float] = []

    async def _capture_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(
        "iguanatrader.shared.heartbeat.asyncio.sleep",
        _capture_sleep,
    )
    await channel.reconnect_loop()
    assert channel.state is ConnectionState.CONNECTED
    # 3 failures → 3 sleeps. Canonical schedule [3, 6, 12] ± 20%.
    assert len(sleeps) == 3
    bases = [3.0, 6.0, 12.0]
    for actual, base in zip(sleeps, bases, strict=True):
        assert base * 0.8 <= actual <= base * 1.2, (actual, base)


@pytest.mark.asyncio
async def test_telegram_on_disconnect_fires_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTelegramTransport()
    channel = TelegramChannel(
        transport=transport,
        repository=AsyncMock(),
        service=AsyncMock(),
        message_bus=AsyncMock(),
        tenant_id=uuid4(),
    )
    fire_count = 0

    async def _on_disc() -> None:
        nonlocal fire_count
        fire_count += 1

    monkeypatch.setattr(channel, "_on_disconnect", _on_disc)
    channel.mark_connected()
    await channel.mark_disconnected()
    await channel.mark_disconnected()  # idempotent
    await channel.mark_disconnected()  # idempotent
    assert fire_count == 1


@pytest.mark.asyncio
async def test_pending_request_survives_outage_and_resolves_post_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resilience smoke: a pending request remains intact across a drop."""
    from iguanatrader.contexts.approval.channels.types import (
        ApprovalRequestRow,
        IncomingCommand,
    )

    transport = FakeTelegramTransport()
    transport.simulate_health_failure(1)
    repo = AsyncMock()
    repo.is_sender_authorized = AsyncMock(return_value=(True, uuid4()))
    service = AsyncMock()
    service.record_decision = AsyncMock(
        return_value=type(
            "Stub",
            (),
            {
                "id": uuid4(),
                "created_at": __import__("datetime").datetime.now(),
            },
        )()
    )
    tenant_id = uuid4()
    channel = TelegramChannel(
        transport=transport,
        repository=repo,
        service=service,
        message_bus=AsyncMock(),
        tenant_id=tenant_id,
    )

    pending: ApprovalRequestRow = ApprovalRequestRow(
        id=uuid4(),
        tenant_id=tenant_id,
        proposal_id=uuid4(),
        delivered_to_channels=["telegram"],
        timeout_seconds=60,
        expires_at=__import__("datetime").datetime.now(),
        created_at=__import__("datetime").datetime.now(),
    )

    # Survive the drop.
    channel.mark_connected()
    await channel.mark_disconnected()

    async def _capture_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "iguanatrader.shared.heartbeat.asyncio.sleep",
        _capture_sleep,
    )
    await channel.reconnect_loop()
    assert channel.state is ConnectionState.CONNECTED

    # Inbound /approve post-reconnect.
    transport.inject_inbound(
        IncomingCommand(
            command_name="/approve",
            raw_args="",
            sender_external_id="user-1",
            channel="telegram",
            tenant_id=tenant_id,
            request_id=pending.id,
        )
    )
    # Reset dispatcher dedup so this test is order-independent.
    from iguanatrader.contexts.approval.channels.command_handler import (
        reset_idempotency_cache,
    )

    reset_idempotency_cache()

    await channel.start_listening()
    service.record_decision.assert_awaited_once()
