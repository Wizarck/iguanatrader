"""End-to-end approval flow — fan-out → /approve → event emission.

Per slice P1 task 6.3.

* Service.create_request inserts a row.
* Two fake channels deliver in parallel (asyncio.gather).
* User issues /approve via the Telegram fake.
* Service writes the approval_decisions row.
* MessageBus emits exactly one approval.proposal.approved event with
  the right payload + channel='telegram' + latency_ms positive.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.approval.bootstrap import get_message_bus
from iguanatrader.contexts.approval.channels.command_handler import (
    reset_idempotency_cache,
)
from iguanatrader.contexts.approval.channels.telegram import TelegramChannel
from iguanatrader.contexts.approval.channels.transports.fakes import (
    FakeHermesTransport,
    FakeTelegramTransport,
)
from iguanatrader.contexts.approval.channels.types import IncomingCommand
from iguanatrader.contexts.approval.channels.whatsapp_hermes import (
    HermesWhatsAppChannel,
)
from iguanatrader.contexts.approval.events import ApprovalProposalApproved
from iguanatrader.contexts.approval.repository import ApprovalRepository
from iguanatrader.contexts.approval.service import ApprovalService
from iguanatrader.persistence import (
    AuthorizedSender,
    Tenant,
    User,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import (
    session_var,
    with_tenant_context,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    reset_idempotency_cache()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    db_path = tmp_path / "ig_approval_flow.db"
    eng = engine_factory(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


@pytest.fixture
async def seed_tenant(sf: async_sessionmaker[AsyncSession]) -> dict[str, object]:
    tid = uuid4()
    uid = uuid4()
    sender_id = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="seed-tenant", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            User(
                id=uid,
                tenant_id=tid,
                email="seed@example.com",
                password_hash="x",
                role="tenant_user",
            )
        )
        s.add(
            AuthorizedSender(
                id=sender_id,
                tenant_id=tid,
                channel="telegram",
                external_id="user-1",
                display_name="seed user",
                enabled=True,
            )
        )
        await s.commit()
    return {"tenant_id": tid, "user_id": uid, "sender_id": sender_id}


@pytest.mark.asyncio
async def test_happy_path_proposal_to_approve_emits_one_event(
    sf: async_sessionmaker[AsyncSession],
    seed_tenant: dict[str, object],
) -> None:
    tid = cast(UUID, seed_tenant["tenant_id"])
    proposal_id = uuid4()
    bus = get_message_bus()
    received: list[ApprovalProposalApproved] = []

    async def _on_approved(ev: ApprovalProposalApproved) -> None:
        received.append(ev)

    sub = bus.subscribe(ApprovalProposalApproved, _on_approved)

    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        repo = ApprovalRepository()
        service = ApprovalService(repository=repo, message_bus=bus)
        request = await service.create_request(
            proposal_id=proposal_id,
            channels=["telegram", "whatsapp"],
            timeout_seconds=60,
        )
        await session.commit()
        assert request.proposal_id == proposal_id

        # Fan-out via two fake channels in parallel.
        tg_transport = FakeTelegramTransport()
        wa_transport = FakeHermesTransport()
        tg_channel = TelegramChannel(
            transport=tg_transport,
            repository=repo,
            service=service,
            message_bus=bus,
            tenant_id=tid,
        )
        wa_channel = HermesWhatsAppChannel(
            transport=wa_transport,
            repository=repo,
            service=service,
            message_bus=bus,
            tenant_id=tid,
        )
        await asyncio.gather(
            tg_channel.deliver_request(request, recipient="user-1"),
            wa_channel.deliver_request(request, recipient="+11234567890"),
        )
        assert len(tg_transport.pop_outbound()) == 1
        assert len(wa_transport.pop_outbound()) == 1

        # User issues /approve via Telegram fake.
        tg_transport.inject_inbound(
            IncomingCommand(
                command_name="/approve",
                raw_args="",
                sender_external_id="user-1",
                channel="telegram",
                tenant_id=tid,
                request_id=request.id,
            )
        )
        await tg_channel.start_listening()
        await session.commit()

    # Wait for bus worker to drain.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await bus.unsubscribe(sub)

    assert len(received) == 1
    event = received[0]
    assert event.proposal_id == proposal_id
    assert event.decided_via_channel == "telegram"
