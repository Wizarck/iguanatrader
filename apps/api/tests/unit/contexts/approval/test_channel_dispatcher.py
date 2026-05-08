"""Unit tests for ``ChannelDispatcher`` wiring (slice p1-followup-channel-fanout)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from iguanatrader.contexts.approval.channels.types import ApprovalRequestRow
from iguanatrader.contexts.approval.dispatcher import (
    LogOnlyChannelDispatcher,
    build_channel_dispatcher_from_env,
)
from iguanatrader.contexts.approval.service import ApprovalService
from iguanatrader.contexts.trading.events import ApprovalRequested
from iguanatrader.shared.messagebus import MessageBus


def _make_request_row() -> ApprovalRequestRow:
    return ApprovalRequestRow(
        id=uuid4(),
        tenant_id=uuid4(),
        proposal_id=uuid4(),
        delivered_to_channels=["telegram", "dashboard"],
        timeout_seconds=300,
        expires_at=datetime.now(UTC) + timedelta(seconds=300),
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_log_only_dispatcher_logs_without_raising() -> None:
    dispatcher = LogOnlyChannelDispatcher()
    # MUST NOT raise.
    await dispatcher.fanout(
        request=_make_request_row(),
        channels=["telegram", "dashboard"],
    )


def test_build_channel_dispatcher_unset_returns_log_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IGUANATRADER_CHANNEL_DISPATCHER", raising=False)
    d = build_channel_dispatcher_from_env()
    assert isinstance(d, LogOnlyChannelDispatcher)


def test_build_channel_dispatcher_unknown_kind_falls_back_to_log_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IGUANATRADER_CHANNEL_DISPATCHER", "made_up_kind")
    d = build_channel_dispatcher_from_env()
    assert isinstance(d, LogOnlyChannelDispatcher)


@pytest.mark.asyncio
async def test_approval_service_calls_dispatcher_after_create_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = AsyncMock()
    fake_repo.create_request = AsyncMock(return_value=_make_request_row())
    dispatcher = AsyncMock()
    dispatcher.fanout = AsyncMock()
    bus = MessageBus()
    service = ApprovalService(
        repository=fake_repo,
        message_bus=bus,
        channel_dispatcher=dispatcher,
    )
    await service._approval_requested_handler(
        ApprovalRequested(
            tenant_id=uuid4(),
            proposal_id=uuid4(),
            decision="allow",
        )
    )
    dispatcher.fanout.assert_awaited_once()
    fake_repo.create_request.assert_awaited_once()


@pytest.mark.asyncio
async def test_approval_service_swallows_dispatcher_failure() -> None:
    fake_repo = AsyncMock()
    fake_repo.create_request = AsyncMock(return_value=_make_request_row())
    failing = AsyncMock()
    failing.fanout = AsyncMock(side_effect=RuntimeError("transport down"))
    bus = MessageBus()
    service = ApprovalService(
        repository=fake_repo,
        message_bus=bus,
        channel_dispatcher=failing,
    )
    # MUST NOT raise.
    await service._approval_requested_handler(
        ApprovalRequested(
            tenant_id=uuid4(),
            proposal_id=uuid4(),
            decision="allow",
        )
    )
    failing.fanout.assert_awaited_once()


@pytest.mark.asyncio
async def test_approval_service_skips_fanout_when_dispatcher_none() -> None:
    fake_repo = AsyncMock()
    fake_repo.create_request = AsyncMock(return_value=_make_request_row())
    bus = MessageBus()
    service = ApprovalService(
        repository=fake_repo,
        message_bus=bus,
        channel_dispatcher=None,
    )
    # MUST NOT raise; dispatcher path skipped.
    await service._approval_requested_handler(
        ApprovalRequested(
            tenant_id=uuid4(),
            proposal_id=uuid4(),
            decision="allow",
        )
    )
    fake_repo.create_request.assert_awaited_once()
