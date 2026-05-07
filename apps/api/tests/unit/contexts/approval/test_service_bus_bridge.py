"""Unit tests for :class:`ApprovalService` bus bridge (slice P1-followup §2).

The bridge `register_subscriptions` + 4 handlers close the
approval→execute hop in the T1 archived event pipeline. These tests
mock the ``ApprovalRepository`` (so we don't need a real sqlite + ORM
round-trip) and assert publication of the trading-flavored events that
T4's daemon already consumes.

Pattern: second canonical instance of "bus-bridge follow-up"; mirror
of ``test_service_bus_bridge.py`` for K1-followup.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
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
    ApprovalRequested,
    ProposalApproved,
    ProposalRejected,
)
from iguanatrader.shared.contextvars import tenant_id_var
from iguanatrader.shared.messagebus import MessageBus

_APPROVAL_ENV_VARS = (
    "IGUANATRADER_DEFAULT_APPROVAL_CHANNELS",
    "IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure no ambient env-var leaks between tests."""
    for var in _APPROVAL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def tenant_id() -> Any:
    """Per-test tenant id; not auto-set on ContextVar (test 7 needs unset)."""
    return uuid4()


@pytest.fixture
def bus() -> MessageBus:
    return MessageBus()


@pytest.fixture
def fake_request_row(tenant_id: Any) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        proposal_id=uuid4(),
        delivered_to_channels=["telegram", "dashboard"],
        timeout_seconds=300,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
    )


@pytest.fixture
def repo(fake_request_row: SimpleNamespace) -> AsyncMock:
    repo = AsyncMock()
    repo.create_request = AsyncMock(return_value=fake_request_row)
    return repo


@pytest.fixture
def service(repo: AsyncMock, bus: MessageBus) -> ApprovalService:
    return ApprovalService(repository=repo, message_bus=bus)


async def _drain(bus: MessageBus, *, ticks: int = 20) -> None:
    """Yield to the event loop ``ticks`` times so subscribers run."""
    for _ in range(ticks):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# §2.1-2.3 — Inbound handler env-var parsing.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_handler_creates_request_row_with_env_defaults(
    service: ApprovalService,
    repo: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env-set: CHANNELS=telegram, TIMEOUT=600 → create_request called once."""
    monkeypatch.setenv("IGUANATRADER_DEFAULT_APPROVAL_CHANNELS", "telegram")
    monkeypatch.setenv("IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS", "600")
    proposal_id = uuid4()
    event = ApprovalRequested(
        tenant_id=uuid4(),
        proposal_id=proposal_id,
        decision="allow",
    )

    await service._approval_requested_handler(event)

    repo.create_request.assert_awaited_once_with(
        proposal_id=proposal_id,
        delivered_to_channels=["telegram"],
        timeout_seconds=600,
    )


@pytest.mark.asyncio
async def test_inbound_handler_uses_default_channels_when_env_unset(
    service: ApprovalService,
    repo: AsyncMock,
) -> None:
    """env-unset → defaults: ["telegram", "dashboard"], 300s."""
    proposal_id = uuid4()
    event = ApprovalRequested(
        tenant_id=uuid4(),
        proposal_id=proposal_id,
        decision="allow",
    )

    await service._approval_requested_handler(event)

    repo.create_request.assert_awaited_once_with(
        proposal_id=proposal_id,
        delivered_to_channels=["telegram", "dashboard"],
        timeout_seconds=300,
    )


@pytest.mark.asyncio
async def test_inbound_handler_clamps_timeout_to_valid_range(
    service: ApprovalService,
    repo: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TIMEOUT=999999 → clamp to 86400; TIMEOUT=0 → clamp to 1."""
    proposal_id = uuid4()

    monkeypatch.setenv("IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS", "999999")
    event = ApprovalRequested(
        tenant_id=uuid4(),
        proposal_id=proposal_id,
        decision="allow",
    )
    await service._approval_requested_handler(event)
    assert repo.create_request.await_args_list[-1].kwargs["timeout_seconds"] == 86400

    monkeypatch.setenv("IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS", "0")
    await service._approval_requested_handler(event)
    assert repo.create_request.await_args_list[-1].kwargs["timeout_seconds"] == 1


# ---------------------------------------------------------------------------
# §2.4-2.6 — Outbound bridge translations.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbound_bridge_translates_approved_to_trading_event(
    service: ApprovalService,
    bus: MessageBus,
    tenant_id: Any,
) -> None:
    """ApprovalProposalApproved → trading.ProposalApproved with same ids."""
    captured: list[ProposalApproved] = []

    async def _capture(evt: ProposalApproved) -> None:
        captured.append(evt)

    bus.subscribe(ProposalApproved, _capture)

    proposal_id = uuid4()
    decision_id = uuid4()
    user_id = uuid4()
    decided_at = datetime.now(UTC)

    token = tenant_id_var.set(tenant_id)
    try:
        await service._bridge_to_trading_approved_handler(
            ApprovalProposalApproved(
                proposal_id=proposal_id,
                decision_id=decision_id,
                decided_at=decided_at,
                decided_by_user_id=user_id,
                decided_via_channel="telegram",
            )
        )
        await _drain(bus)
    finally:
        tenant_id_var.reset(token)

    assert len(captured) == 1
    evt = captured[0]
    assert evt.tenant_id == tenant_id
    assert evt.proposal_id == proposal_id
    assert evt.approved_by_user_id == user_id
    assert evt.metadata["decision_id"] == str(decision_id)
    assert evt.metadata["decided_via_channel"] == "telegram"


@pytest.mark.asyncio
async def test_outbound_bridge_translates_rejected_to_trading_event(
    service: ApprovalService,
    bus: MessageBus,
    tenant_id: Any,
) -> None:
    """ApprovalProposalRejected(reason='user_declined') → ProposalRejected same."""
    captured: list[ProposalRejected] = []

    async def _capture(evt: ProposalRejected) -> None:
        captured.append(evt)

    bus.subscribe(ProposalRejected, _capture)

    proposal_id = uuid4()
    decision_id = uuid4()

    token = tenant_id_var.set(tenant_id)
    try:
        await service._bridge_to_trading_rejected_handler(
            ApprovalProposalRejected(
                proposal_id=proposal_id,
                decision_id=decision_id,
                decided_at=datetime.now(UTC),
                reason="user_declined",
                decided_via_channel="dashboard",
            )
        )
        await _drain(bus)
    finally:
        tenant_id_var.reset(token)

    assert len(captured) == 1
    assert captured[0].reason == "user_declined"
    assert captured[0].proposal_id == proposal_id


@pytest.mark.asyncio
async def test_outbound_bridge_translates_timeout_to_trading_rejected_with_sentinel(
    service: ApprovalService,
    bus: MessageBus,
    tenant_id: Any,
) -> None:
    """ApprovalProposalTimedOut → ProposalRejected(reason='approval_timeout')."""
    captured: list[ProposalRejected] = []

    async def _capture(evt: ProposalRejected) -> None:
        captured.append(evt)

    bus.subscribe(ProposalRejected, _capture)

    proposal_id = uuid4()
    request_id = uuid4()

    token = tenant_id_var.set(tenant_id)
    try:
        await service._bridge_to_trading_timeout_handler(
            ApprovalProposalTimedOut(
                proposal_id=proposal_id,
                request_id=request_id,
                expired_at=datetime.now(UTC),
            )
        )
        await _drain(bus)
    finally:
        tenant_id_var.reset(token)

    assert len(captured) == 1
    assert captured[0].reason == "approval_timeout"
    assert captured[0].metadata["request_id"] == str(request_id)


# ---------------------------------------------------------------------------
# §2.7 — ContextVar fallback (no tenant → log + skip).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbound_bridge_skips_when_tenant_context_unset(
    service: ApprovalService,
    bus: MessageBus,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """tenant_id_var unset → no event published + ERROR log emitted."""
    captured: list[ProposalApproved] = []

    async def _capture(evt: ProposalApproved) -> None:
        captured.append(evt)

    bus.subscribe(ProposalApproved, _capture)

    # Reset to ensure unset (test order independence).
    token = tenant_id_var.set(None)
    try:
        with caplog.at_level(logging.ERROR):
            await service._bridge_to_trading_approved_handler(
                ApprovalProposalApproved(
                    proposal_id=uuid4(),
                    decision_id=uuid4(),
                    decided_at=datetime.now(UTC),
                    decided_by_user_id=uuid4(),
                    decided_via_channel="telegram",
                )
            )
        await _drain(bus)
    finally:
        tenant_id_var.reset(token)

    assert captured == []
    assert any(
        "approval.bus.bridge_skipped_no_tenant" in record.getMessage()
        or "bridge_skipped_no_tenant" in str(record.__dict__.get("event", ""))
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# §2.8 — Integration: register_subscriptions wires all four handlers.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_subscriptions_wires_all_four_handlers(
    service: ApprovalService,
    bus: MessageBus,
    repo: AsyncMock,
    tenant_id: Any,
) -> None:
    """Publish all 4 inbound events; assert 1 create + 3 trading events."""
    approved: list[ProposalApproved] = []
    rejected: list[ProposalRejected] = []

    async def _capture_approved(evt: ProposalApproved) -> None:
        approved.append(evt)

    async def _capture_rejected(evt: ProposalRejected) -> None:
        rejected.append(evt)

    bus.subscribe(ProposalApproved, _capture_approved)
    bus.subscribe(ProposalRejected, _capture_rejected)

    service.register_subscriptions(bus)

    token = tenant_id_var.set(tenant_id)
    try:
        await bus.publish(
            ApprovalRequested(
                tenant_id=tenant_id,
                proposal_id=uuid4(),
                decision="allow",
            )
        )
        await bus.publish(
            ApprovalProposalApproved(
                proposal_id=uuid4(),
                decision_id=uuid4(),
                decided_at=datetime.now(UTC),
                decided_by_user_id=uuid4(),
                decided_via_channel="telegram",
            )
        )
        await bus.publish(
            ApprovalProposalRejected(
                proposal_id=uuid4(),
                decision_id=uuid4(),
                decided_at=datetime.now(UTC),
                reason="user_declined",
                decided_via_channel="dashboard",
            )
        )
        await bus.publish(
            ApprovalProposalTimedOut(
                proposal_id=uuid4(),
                request_id=uuid4(),
                expired_at=datetime.now(UTC),
            )
        )
        await _drain(bus, ticks=40)
    finally:
        tenant_id_var.reset(token)

    repo.create_request.assert_awaited_once()
    assert len(approved) == 1
    assert len(rejected) == 2
    reasons = {evt.reason for evt in rejected}
    assert reasons == {"user_declined", "approval_timeout"}

    await bus.aclose()


