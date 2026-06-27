"""WS-5 PR-B: exit-approval bridge semantics + the FAIL-CLOSED action_type guard.

The approval "granted" bridge historically meant OPEN a position
(``ApprovalProposalApproved`` → ``trading.ProposalApproved`` →
``place_order``). WS-5 reuses the same machinery for EXITS via an
``action_type`` discriminator. These tests lock the real-money-critical
invariant: a granted EXIT closes the trade (never buys), a granted ENTRY
opens (never closes), and ANY ambiguity fires NEITHER.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from iguanatrader.contexts.approval.events import (
    ApprovalProposalApproved,
    ApprovalProposalRejected,
    ApprovalProposalTimedOut,
)
from iguanatrader.contexts.approval.service import ApprovalService
from iguanatrader.contexts.trading.events import (
    CloseTradeRequested,
    ExitApprovalRequested,
    ProposalApproved,
    ProposalRejected,
)
from iguanatrader.shared.contextvars import tenant_id_var
from iguanatrader.shared.messagebus import MessageBus


@pytest.fixture
def bus() -> MessageBus:
    return MessageBus()


@pytest.fixture
def tenant_id() -> Any:
    return uuid4()


@pytest.fixture
def service(bus: MessageBus) -> ApprovalService:
    return ApprovalService(repository=AsyncMock(), message_bus=bus)


async def _drain(bus: MessageBus, *, ticks: int = 20) -> None:
    for _ in range(ticks):
        await asyncio.sleep(0)


def _captures(bus: MessageBus) -> tuple[list[Any], list[Any], list[Any]]:
    closes: list[CloseTradeRequested] = []
    buys: list[ProposalApproved] = []
    rejects: list[ProposalRejected] = []

    async def _c(e: CloseTradeRequested) -> None:
        closes.append(e)

    async def _b(e: ProposalApproved) -> None:
        buys.append(e)

    async def _r(e: ProposalRejected) -> None:
        rejects.append(e)

    bus.subscribe(CloseTradeRequested, _c)
    bus.subscribe(ProposalApproved, _b)
    bus.subscribe(ProposalRejected, _r)
    return closes, buys, rejects


@pytest.mark.asyncio
async def test_granted_exit_closes_trade_and_never_buys(
    service: ApprovalService, bus: MessageBus, tenant_id: Any
) -> None:
    closes, buys, _ = _captures(bus)
    trade_id = uuid4()
    token = tenant_id_var.set(tenant_id)
    try:
        await service._bridge_to_trading_approved_handler(
            ApprovalProposalApproved(
                proposal_id=None,
                decision_id=uuid4(),
                decided_at=datetime.now(UTC),
                decided_via_channel="telegram",
                action_type="exit",
                trade_id=trade_id,
            )
        )
        await _drain(bus)
    finally:
        tenant_id_var.reset(token)

    assert len(closes) == 1
    assert closes[0].trade_id == trade_id
    assert closes[0].reason == "manual"
    assert closes[0].tenant_id == tenant_id
    assert closes[0].metadata.get("source") == "urgent_exit_approval"
    assert buys == []  # a granted EXIT must NEVER open a position


@pytest.mark.asyncio
async def test_granted_entry_opens_and_never_closes(
    service: ApprovalService, bus: MessageBus, tenant_id: Any
) -> None:
    closes, buys, _ = _captures(bus)
    proposal_id = uuid4()
    token = tenant_id_var.set(tenant_id)
    try:
        await service._bridge_to_trading_approved_handler(
            ApprovalProposalApproved(
                proposal_id=proposal_id,
                decision_id=uuid4(),
                decided_at=datetime.now(UTC),
                decided_via_channel="dashboard",
                action_type="entry",
            )
        )
        await _drain(bus)
    finally:
        tenant_id_var.reset(token)

    assert len(buys) == 1
    assert buys[0].proposal_id == proposal_id
    assert closes == []


@pytest.mark.asyncio
async def test_granted_unknown_action_type_fires_nothing(
    service: ApprovalService, bus: MessageBus, tenant_id: Any
) -> None:
    closes, buys, _ = _captures(bus)
    token = tenant_id_var.set(tenant_id)
    try:
        await service._bridge_to_trading_approved_handler(
            ApprovalProposalApproved(
                proposal_id=uuid4(),
                decision_id=uuid4(),
                decided_via_channel="telegram",
                action_type="something_unexpected",
                trade_id=uuid4(),
            )
        )
        await _drain(bus)
    finally:
        tenant_id_var.reset(token)

    # FAIL-CLOSED: an unrecognised discriminator opens nothing and closes nothing.
    assert buys == []
    assert closes == []


@pytest.mark.asyncio
async def test_granted_exit_without_trade_id_fires_nothing(
    service: ApprovalService, bus: MessageBus, tenant_id: Any
) -> None:
    closes, buys, _ = _captures(bus)
    token = tenant_id_var.set(tenant_id)
    try:
        await service._bridge_to_trading_approved_handler(
            ApprovalProposalApproved(
                proposal_id=None,
                decision_id=uuid4(),
                decided_via_channel="telegram",
                action_type="exit",
                trade_id=None,  # malformed exit
            )
        )
        await _drain(bus)
    finally:
        tenant_id_var.reset(token)

    assert closes == []
    assert buys == []


@pytest.mark.asyncio
async def test_rejected_exit_keeps_position_open_no_proposal_rejected(
    service: ApprovalService, bus: MessageBus, tenant_id: Any
) -> None:
    closes, _, rejects = _captures(bus)
    token = tenant_id_var.set(tenant_id)
    try:
        await service._bridge_to_trading_rejected_handler(
            ApprovalProposalRejected(
                proposal_id=None,
                decision_id=uuid4(),
                decided_at=datetime.now(UTC),
                reason="user_declined",
                decided_via_channel="telegram",
                action_type="exit",
                trade_id=uuid4(),
            )
        )
        await _drain(bus)
    finally:
        tenant_id_var.reset(token)

    # Declined exit: position stays open — no close, no ProposalRejected.
    assert closes == []
    assert rejects == []


@pytest.mark.asyncio
async def test_timeout_exit_no_proposal_rejected(
    service: ApprovalService, bus: MessageBus, tenant_id: Any
) -> None:
    closes, _, rejects = _captures(bus)
    token = tenant_id_var.set(tenant_id)
    try:
        await service._bridge_to_trading_timeout_handler(
            ApprovalProposalTimedOut(
                proposal_id=None,
                request_id=uuid4(),
                expired_at=datetime.now(UTC),
                action_type="exit",
                trade_id=uuid4(),
            )
        )
        await _drain(bus)
    finally:
        tenant_id_var.reset(token)

    assert closes == []
    assert rejects == []


@pytest.mark.asyncio
async def test_inbound_exit_request_creates_exit_row_and_fans_out(
    bus: MessageBus, tenant_id: Any
) -> None:
    dispatcher = AsyncMock()
    dispatcher.fanout = AsyncMock()
    repo = AsyncMock()
    repo.create_request = AsyncMock(
        return_value=SimpleNamespace(id=uuid4(), expires_at=datetime.now(UTC))
    )
    service = ApprovalService(repository=repo, message_bus=bus, channel_dispatcher=dispatcher)
    trade_id = uuid4()

    await service._exit_approval_requested_handler(
        ExitApprovalRequested(
            tenant_id=tenant_id,
            trade_id=trade_id,
            symbol="AAPL",
            side="buy",
            quantity=Decimal("10"),
            reason="urgent",
        )
    )

    # Persisted as an exit row keyed on trade_id, NOT a proposal.
    call = repo.create_request.await_args
    assert call is not None
    assert call.kwargs["action_type"] == "exit"
    assert call.kwargs["trade_id"] == trade_id
    assert call.kwargs["proposal_id"] is None
    dispatcher.fanout.assert_awaited_once()
