"""Unit tests for :class:`TelegramBotMessageDispatcher`."""

from __future__ import annotations

import pytest
from iguanatrader.shared.channel_dispatch import (
    AsyncTokenBucket,
    OutboundMessage,
    Recipient,
)
from iguanatrader.shared.channel_dispatch.adapters.telegram import (
    TELEGRAM_CHANNEL,
    TelegramBotMessageDispatcher,
)


class _FakeTelegramTransport:
    """Records send calls; returns a deterministic wire id."""

    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.actions_seen: list[tuple[tuple[str, str], ...]] = []
        self._fail_on = fail_on or set()

    async def send(
        self, *, address: str, body: str, actions: tuple[tuple[str, str], ...] = ()
    ) -> str:
        self.calls.append((address, body))
        self.actions_seen.append(actions)
        if address in self._fail_on:
            raise RuntimeError(f"forced failure for {address}")
        return f"tg-{address}"


def _make_message() -> OutboundMessage:
    return OutboundMessage(body="approve?", correlation_id="corr-1")


def test_constructor_requires_transport_or_bot_token() -> None:
    with pytest.raises(ValueError):
        TelegramBotMessageDispatcher()


@pytest.mark.asyncio
async def test_delivers_to_telegram_recipients() -> None:
    transport = _FakeTelegramTransport()
    bucket = AsyncTokenBucket(rate_per_second=1000.0, burst=10)
    dispatcher = TelegramBotMessageDispatcher(transport=transport, rate_limit=bucket)
    recipients = [
        Recipient(channel=TELEGRAM_CHANNEL, address="111"),
        Recipient(channel=TELEGRAM_CHANNEL, address="222"),
    ]
    results = await dispatcher.dispatch(message=_make_message(), recipients=recipients)
    assert len(results) == 2
    assert all(r.status == "delivered" for r in results)
    assert results[0].wire_message_id == "tg-111"
    assert results[1].wire_message_id == "tg-222"
    assert transport.calls == [("111", "approve?"), ("222", "approve?")]


@pytest.mark.asyncio
async def test_passes_inline_action_buttons_to_transport() -> None:
    transport = _FakeTelegramTransport()
    dispatcher = TelegramBotMessageDispatcher(
        transport=transport,
        rate_limit=AsyncTokenBucket(rate_per_second=1000.0, burst=10),
    )
    actions = (("✅ Aprobar", "approve:req-9"), ("❌ Rechazar", "reject:req-9"))
    message = OutboundMessage(body="approve?", correlation_id="req-9", actions=actions)
    await dispatcher.dispatch(
        message=message, recipients=[Recipient(channel=TELEGRAM_CHANNEL, address="111")]
    )
    assert transport.actions_seen == [actions]


@pytest.mark.asyncio
async def test_skips_non_telegram_recipients() -> None:
    transport = _FakeTelegramTransport()
    dispatcher = TelegramBotMessageDispatcher(
        transport=transport,
        rate_limit=AsyncTokenBucket(rate_per_second=1000.0, burst=10),
    )
    recipients = [
        Recipient(channel="whatsapp", address="+34111"),
        Recipient(channel=TELEGRAM_CHANNEL, address="222"),
    ]
    results = await dispatcher.dispatch(message=_make_message(), recipients=recipients)
    assert len(results) == 2
    assert results[0].status == "skipped"
    assert results[0].error is not None and "channel='whatsapp'" in results[0].error
    assert results[1].status == "delivered"
    assert transport.calls == [("222", "approve?")]


@pytest.mark.asyncio
async def test_per_recipient_transport_failure_does_not_break_batch() -> None:
    transport = _FakeTelegramTransport(fail_on={"111"})
    dispatcher = TelegramBotMessageDispatcher(
        transport=transport,
        rate_limit=AsyncTokenBucket(rate_per_second=1000.0, burst=10),
    )
    recipients = [
        Recipient(channel=TELEGRAM_CHANNEL, address="111"),
        Recipient(channel=TELEGRAM_CHANNEL, address="222"),
    ]
    results = await dispatcher.dispatch(message=_make_message(), recipients=recipients)
    assert results[0].status == "failed"
    assert results[0].error is not None and "forced failure" in results[0].error
    assert results[1].status == "delivered"


@pytest.mark.asyncio
async def test_rate_limiter_is_consulted() -> None:
    transport = _FakeTelegramTransport()

    class _CountingBucket:
        def __init__(self) -> None:
            self.acquired = 0

        async def acquire(self) -> None:
            self.acquired += 1

    bucket = _CountingBucket()
    dispatcher = TelegramBotMessageDispatcher(transport=transport, rate_limit=bucket)
    recipients = [
        Recipient(channel=TELEGRAM_CHANNEL, address="111"),
        Recipient(channel="whatsapp", address="+34222"),  # skipped, no acquire
        Recipient(channel=TELEGRAM_CHANNEL, address="333"),
    ]
    await dispatcher.dispatch(message=_make_message(), recipients=recipients)
    assert bucket.acquired == 2
