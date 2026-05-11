"""Unit tests for :class:`MultiChannelMessageDispatcher`."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from iguanatrader.shared.channel_dispatch import (
    DispatchResult,
    MultiChannelMessageDispatcher,
    OutboundMessage,
    Recipient,
)


def _make_message() -> OutboundMessage:
    return OutboundMessage(body="hi", correlation_id="corr-1")


class _StubDispatcher:
    def __init__(self, *, status: str, wire_id_prefix: str) -> None:
        self.status = status
        self.prefix = wire_id_prefix
        self.calls: list[Sequence[Recipient]] = []

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        self.calls.append(list(recipients))
        return [
            DispatchResult(
                channel=r.channel,
                address=r.address,
                status=self.status,  # type: ignore[arg-type]
                wire_message_id=(
                    f"{self.prefix}-{r.address}" if self.status == "delivered" else None
                ),
                error=None,
            )
            for r in recipients
        ]


class _RaisingDispatcher:
    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        raise RuntimeError("transport down")


class _OmittingDispatcher:
    """Returns fewer results than recipients — used to assert MultiChannel
    fills the gap with status='failed'."""

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        return [
            DispatchResult(
                channel=recipients[0].channel,
                address=recipients[0].address,
                status="delivered",
                wire_message_id="ok-0",
                error=None,
            )
        ]


@pytest.mark.asyncio
async def test_multi_routes_per_channel() -> None:
    telegram = _StubDispatcher(status="delivered", wire_id_prefix="tg")
    whatsapp = _StubDispatcher(status="delivered", wire_id_prefix="wa")
    multi = MultiChannelMessageDispatcher(dispatchers={"telegram": telegram, "whatsapp": whatsapp})
    recipients = [
        Recipient(channel="telegram", address="111"),
        Recipient(channel="whatsapp", address="+34222"),
        Recipient(channel="telegram", address="333"),
    ]
    results = await multi.dispatch(message=_make_message(), recipients=recipients)
    assert len(results) == 3
    # Order preserves input order.
    assert results[0].channel == "telegram" and results[0].address == "111"
    assert results[1].channel == "whatsapp" and results[1].address == "+34222"
    assert results[2].channel == "telegram" and results[2].address == "333"
    assert all(r.status == "delivered" for r in results)
    # Telegram stub received both telegram recipients in one call.
    assert len(telegram.calls) == 1
    assert {r.address for r in telegram.calls[0]} == {"111", "333"}
    # WhatsApp stub received only the whatsapp recipient.
    assert len(whatsapp.calls) == 1
    assert [r.address for r in whatsapp.calls[0]] == ["+34222"]


@pytest.mark.asyncio
async def test_multi_unknown_channel_returns_skipped() -> None:
    multi = MultiChannelMessageDispatcher(dispatchers={})
    recipients = [Recipient(channel="signal", address="@me")]
    results = await multi.dispatch(message=_make_message(), recipients=recipients)
    assert len(results) == 1
    assert results[0].status == "skipped"
    assert results[0].error is not None
    assert "no dispatcher" in results[0].error
    assert "signal" in results[0].error


@pytest.mark.asyncio
async def test_multi_isolates_failing_dispatcher() -> None:
    good = _StubDispatcher(status="delivered", wire_id_prefix="tg")
    multi = MultiChannelMessageDispatcher(
        dispatchers={"telegram": good, "whatsapp": _RaisingDispatcher()}
    )
    recipients = [
        Recipient(channel="telegram", address="111"),
        Recipient(channel="whatsapp", address="+34222"),
    ]
    results = await multi.dispatch(message=_make_message(), recipients=recipients)
    assert len(results) == 2
    telegram_result = next(r for r in results if r.channel == "telegram")
    whatsapp_result = next(r for r in results if r.channel == "whatsapp")
    assert telegram_result.status == "delivered"
    assert whatsapp_result.status == "failed"
    assert whatsapp_result.error is not None
    assert "RuntimeError" in whatsapp_result.error


@pytest.mark.asyncio
async def test_multi_fills_omitted_results_with_failed() -> None:
    multi = MultiChannelMessageDispatcher(dispatchers={"telegram": _OmittingDispatcher()})
    recipients = [
        Recipient(channel="telegram", address="111"),
        Recipient(channel="telegram", address="222"),
    ]
    results = await multi.dispatch(message=_make_message(), recipients=recipients)
    assert len(results) == 2
    assert results[0].address == "111" and results[0].status == "delivered"
    assert results[1].address == "222" and results[1].status == "failed"
    assert results[1].error is not None
    assert "omitted" in results[1].error


@pytest.mark.asyncio
async def test_multi_empty_recipients() -> None:
    multi = MultiChannelMessageDispatcher(dispatchers={})
    results = await multi.dispatch(message=_make_message(), recipients=[])
    assert results == []
