"""Hypothesis property tests for :meth:`ApprovalService._approval_requested_handler`.

Slice ``property-tests-bus-bridge-handlers``. Companion to the propose +
risk handler property suites. Covers the third hop in the
propose→risk→approve→execute bus chain.

Four invariants under test:

1. Exactly 1 ``create_request`` call per ``ApprovalRequested`` event.
2. Dispatcher present → exactly 1 ``dispatcher.fanout(request, channels)``
   call after the audit-write.
3. ``channel_dispatcher=None`` → zero fanout calls, audit-write still runs.
4. Dispatcher raises → handler MUST NOT re-raise (FR32 isolation); the
   audit-write still completes.

Marker: ``@pytest.mark.property``. NOT ``ci_blocking`` — emission contract
already covered by unit tests; regression net for random event payloads
+ dispatcher behaviours.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from iguanatrader.contexts.approval.channels.types import ApprovalRequestRow
from iguanatrader.contexts.approval.service import ApprovalService
from iguanatrader.contexts.trading.events import ApprovalRequested
from iguanatrader.shared.messagebus import MessageBus


def _make_request_row(*, tenant_id: UUID, proposal_id: UUID) -> ApprovalRequestRow:
    return ApprovalRequestRow(
        id=uuid4(),
        tenant_id=tenant_id,
        proposal_id=proposal_id,
        delivered_to_channels=["telegram", "dashboard"],
        timeout_seconds=300,
        expires_at=datetime.now(UTC) + timedelta(seconds=300),
        created_at=datetime.now(UTC),
    )


@pytest.mark.property
@given(
    proposal_uuid_bytes=st.binary(min_size=16, max_size=16),
    tenant_uuid_bytes=st.binary(min_size=16, max_size=16),
    decision=st.sampled_from(["allow", "review_required"]),
)
@settings(
    deadline=None,
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_handler_creates_exactly_one_request_per_event(
    proposal_uuid_bytes: bytes,
    tenant_uuid_bytes: bytes,
    decision: str,
) -> None:
    """For any ApprovalRequested, exactly 1 create_request call."""

    async def _run() -> None:
        tenant_id = UUID(bytes=tenant_uuid_bytes)
        proposal_id = UUID(bytes=proposal_uuid_bytes)

        fake_repo = AsyncMock()
        fake_repo.create_request = AsyncMock(
            return_value=_make_request_row(tenant_id=tenant_id, proposal_id=proposal_id)
        )

        bus = MessageBus()
        service = ApprovalService(
            repository=fake_repo,
            message_bus=bus,
            channel_dispatcher=None,
        )

        event = ApprovalRequested(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            decision=decision,
        )
        await service._approval_requested_handler(event)

        assert fake_repo.create_request.await_count == 1
        await bus.aclose()

    asyncio.run(_run())


@pytest.mark.property
@given(
    proposal_uuid_bytes=st.binary(min_size=16, max_size=16),
    tenant_uuid_bytes=st.binary(min_size=16, max_size=16),
)
@settings(
    deadline=None,
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_handler_invokes_dispatcher_when_wired(
    proposal_uuid_bytes: bytes,
    tenant_uuid_bytes: bytes,
) -> None:
    """Dispatcher wired → exactly 1 fanout(request, channels) call after create_request."""

    async def _run() -> None:
        tenant_id = UUID(bytes=tenant_uuid_bytes)
        proposal_id = UUID(bytes=proposal_uuid_bytes)
        row = _make_request_row(tenant_id=tenant_id, proposal_id=proposal_id)

        fake_repo = AsyncMock()
        fake_repo.create_request = AsyncMock(return_value=row)

        dispatcher = AsyncMock()
        dispatcher.fanout = AsyncMock()

        bus = MessageBus()
        service = ApprovalService(
            repository=fake_repo,
            message_bus=bus,
            channel_dispatcher=dispatcher,
        )

        event = ApprovalRequested(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            decision="allow",
        )
        await service._approval_requested_handler(event)

        assert fake_repo.create_request.await_count == 1
        assert dispatcher.fanout.await_count == 1
        # fanout receives the row + the channels list (kw-only).
        call = dispatcher.fanout.call_args
        assert call.kwargs["request"].id == row.id
        assert isinstance(call.kwargs["channels"], list)
        await bus.aclose()

    asyncio.run(_run())


@pytest.mark.property
@given(
    proposal_uuid_bytes=st.binary(min_size=16, max_size=16),
    tenant_uuid_bytes=st.binary(min_size=16, max_size=16),
    error_message=st.text(min_size=0, max_size=80),
)
@settings(
    deadline=None,
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_handler_swallows_dispatcher_exception(
    proposal_uuid_bytes: bytes,
    tenant_uuid_bytes: bytes,
    error_message: str,
) -> None:
    """FR32: a raising dispatcher MUST NOT propagate out of the handler.

    create_request still completes (audit-write protected); dispatcher
    failure is logged + swallowed.
    """

    async def _run() -> None:
        tenant_id = UUID(bytes=tenant_uuid_bytes)
        proposal_id = UUID(bytes=proposal_uuid_bytes)
        row = _make_request_row(tenant_id=tenant_id, proposal_id=proposal_id)

        fake_repo = AsyncMock()
        fake_repo.create_request = AsyncMock(return_value=row)

        dispatcher = AsyncMock()
        dispatcher.fanout = AsyncMock(side_effect=RuntimeError(error_message or "boom"))

        bus = MessageBus()
        service = ApprovalService(
            repository=fake_repo,
            message_bus=bus,
            channel_dispatcher=dispatcher,
        )

        event = ApprovalRequested(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            decision="allow",
        )
        # MUST NOT raise.
        await service._approval_requested_handler(event)

        # Audit-write still happened; dispatcher was attempted exactly once.
        assert fake_repo.create_request.await_count == 1
        assert dispatcher.fanout.await_count == 1
        await bus.aclose()

    asyncio.run(_run())


@pytest.mark.property
@given(
    proposal_uuid_bytes=st.binary(min_size=16, max_size=16),
    tenant_uuid_bytes=st.binary(min_size=16, max_size=16),
)
@settings(
    deadline=None,
    max_examples=30,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_handler_no_dispatcher_makes_zero_fanout_calls(
    proposal_uuid_bytes: bytes,
    tenant_uuid_bytes: bytes,
) -> None:
    """channel_dispatcher=None → audit-write only, no fanout side effects."""

    async def _run() -> None:
        tenant_id = UUID(bytes=tenant_uuid_bytes)
        proposal_id = UUID(bytes=proposal_uuid_bytes)
        row = _make_request_row(tenant_id=tenant_id, proposal_id=proposal_id)

        fake_repo = AsyncMock()
        fake_repo.create_request = AsyncMock(return_value=row)

        bus = MessageBus()
        service = ApprovalService(
            repository=fake_repo,
            message_bus=bus,
            channel_dispatcher=None,
        )

        event = ApprovalRequested(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            decision="allow",
        )
        await service._approval_requested_handler(event)

        assert fake_repo.create_request.await_count == 1
        await bus.aclose()

    asyncio.run(_run())
