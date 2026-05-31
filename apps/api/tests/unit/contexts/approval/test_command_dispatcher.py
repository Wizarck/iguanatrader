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
    tenant_id: Any = None,
) -> IncomingCommand:
    # #39: the in-process dedup cache is tenant-keyed, so a "duplicate"
    # must share a tenant_id to collapse. Callers that exercise dedup
    # pass an explicit, shared tenant_id; everyone else gets a fresh one.
    return IncomingCommand(
        command_name=command,
        raw_args="",
        sender_external_id="ext-123",
        channel="telegram",
        tenant_id=tenant_id if tenant_id is not None else uuid4(),
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
    tenant_id = uuid4()  # #39: a real duplicate is same-tenant.
    service = AsyncMock()
    service.record_decision = AsyncMock(
        return_value=type(
            "DecisionStub",
            (),
            {"id": uuid4(), "created_at": __import__("datetime").datetime.now()},
        )()
    )
    incoming1 = _make_incoming("/approve", request_id=request_id, tenant_id=tenant_id)
    incoming2 = _make_incoming("/approve", request_id=request_id, tenant_id=tenant_id)
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


@pytest.mark.asyncio
async def test_dispatch_does_not_dedup_same_request_across_tenants() -> None:
    """#39: the dedup cache is tenant-keyed — an identical request_id in a
    different tenant must NOT be suppressed by another tenant's command."""
    request_id = uuid4()
    service = AsyncMock()
    service.record_decision = AsyncMock(
        return_value=type(
            "DecisionStub",
            (),
            {"id": uuid4(), "created_at": __import__("datetime").datetime.now()},
        )()
    )
    incoming_a = _make_incoming("/approve", request_id=request_id, tenant_id=uuid4())
    incoming_b = _make_incoming("/approve", request_id=request_id, tenant_id=uuid4())
    await dispatch(incoming_a, service=service, message_bus=AsyncMock(), repository=AsyncMock())
    await dispatch(incoming_b, service=service, message_bus=AsyncMock(), repository=AsyncMock())
    # Two distinct tenants → no cross-tenant dedup → both reach the handler.
    assert service.record_decision.await_count == 2


@pytest.mark.asyncio
async def test_dispatch_denies_approve_when_approvals_paused(monkeypatch: Any) -> None:
    """#31: a trade-actuating command is denied while ``approvals_paused``
    reads True for the tenant — even for an authorised caller."""
    import iguanatrader.contexts.approval.channels.command_handler as ch

    async def _paused(_tenant_id: Any) -> bool:
        return True

    monkeypatch.setattr(ch, "_approvals_paused", _paused)
    service = AsyncMock()
    result = await dispatch(
        _make_incoming("/approve", request_id=uuid4()),
        service=service,
        message_bus=AsyncMock(),
        repository=AsyncMock(),
    )
    assert result.status == "denied"
    assert "paused" in result.message.lower()
    service.record_decision.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_allows_reject_when_approvals_paused(monkeypatch: Any) -> None:
    """#31: resolving commands (/reject) still flow while paused — a paused
    operator can clear the backlog; only trade-actuating commands gate."""
    import iguanatrader.contexts.approval.channels.command_handler as ch

    async def _paused(_tenant_id: Any) -> bool:
        return True

    monkeypatch.setattr(ch, "_approvals_paused", _paused)
    result = await dispatch(
        _make_incoming("/reject", request_id=uuid4()),
        service=AsyncMock(),
        message_bus=AsyncMock(),
        repository=AsyncMock(),
    )
    # /reject is not blocked_when_paused → it reaches its handler (status ok).
    assert result.status != "denied"
