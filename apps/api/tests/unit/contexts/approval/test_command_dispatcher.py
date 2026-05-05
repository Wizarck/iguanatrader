"""Dispatcher unit tests — routing, role gate, unknown command, dedup.

Per slice P1 task 6.6.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from iguanatrader.contexts.approval.channels.command_handler import (
    dispatch,
    reset_idempotency_cache,
)
from iguanatrader.contexts.approval.channels.types import IncomingCommand


@pytest.fixture(autouse=True)
def _reset_dedup() -> None:
    reset_idempotency_cache()


def _make_incoming(
    command: str,
    *,
    role: str = "user",
    request_id: Any = None,
) -> IncomingCommand:
    return IncomingCommand(
        command_name=command,
        raw_args="",
        sender_external_id="ext-123",
        channel="telegram",
        tenant_id=uuid4(),
        request_id=request_id,
        role=role,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_dispatch_routes_positions_to_handler() -> None:
    incoming = _make_incoming("/positions")
    result = await dispatch(
        incoming,
        service=AsyncMock(),
        message_bus=AsyncMock(),
        repository=AsyncMock(),
    )
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_dispatch_denies_admin_command_for_user_role() -> None:
    incoming = _make_incoming("/halt", role="user")
    result = await dispatch(
        incoming,
        service=AsyncMock(),
        message_bus=AsyncMock(),
        repository=AsyncMock(),
    )
    assert result.status == "denied"
    assert "admin" in result.message.lower()


@pytest.mark.asyncio
async def test_dispatch_unknown_command_returns_unknown_command() -> None:
    incoming = _make_incoming("/not-a-real-command")
    result = await dispatch(
        incoming,
        service=AsyncMock(),
        message_bus=AsyncMock(),
        repository=AsyncMock(),
    )
    assert result.status == "unknown_command"


@pytest.mark.asyncio
async def test_dispatch_dedups_duplicate_approve_via_in_process_cache() -> None:
    request_id = uuid4()
    service = AsyncMock()
    service.record_decision = AsyncMock(
        return_value=type(
            "DecisionStub",
            (),
            {"id": uuid4(), "created_at": __import__("datetime").datetime.now()},
        )()
    )
    incoming1 = _make_incoming("/approve", request_id=request_id)
    incoming2 = _make_incoming("/approve", request_id=request_id)
    r1 = await dispatch(
        incoming1,
        service=service,
        message_bus=AsyncMock(),
        repository=AsyncMock(),
    )
    r2 = await dispatch(
        incoming2,
        service=service,
        message_bus=AsyncMock(),
        repository=AsyncMock(),
    )
    assert r1.status == "ok"
    assert r2.status == "ok"
    # Second call short-circuits via the in-process cache → service
    # was called exactly once.
    assert service.record_decision.await_count == 1
