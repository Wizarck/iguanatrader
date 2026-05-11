"""Unit tests for :class:`LogOnlyMessageDispatcher`."""

from __future__ import annotations

import pytest
from iguanatrader.shared.channel_dispatch import (
    LogOnlyMessageDispatcher,
    OutboundMessage,
    Recipient,
)


def _make_message() -> OutboundMessage:
    return OutboundMessage(body="hello", correlation_id="corr-1")


@pytest.mark.asyncio
async def test_log_only_returns_one_skipped_result_per_recipient() -> None:
    dispatcher = LogOnlyMessageDispatcher()
    recipients = [
        Recipient(channel="telegram", address="111"),
        Recipient(channel="whatsapp", address="+34111"),
    ]
    results = await dispatcher.dispatch(message=_make_message(), recipients=recipients)
    assert len(results) == 2
    assert all(r.status == "skipped" for r in results)
    assert [r.channel for r in results] == ["telegram", "whatsapp"]
    assert [r.address for r in results] == ["111", "+34111"]
    assert all(r.wire_message_id is None and r.error is None for r in results)


@pytest.mark.asyncio
async def test_log_only_with_empty_recipients_returns_empty_list() -> None:
    dispatcher = LogOnlyMessageDispatcher()
    results = await dispatcher.dispatch(message=_make_message(), recipients=[])
    assert results == []
