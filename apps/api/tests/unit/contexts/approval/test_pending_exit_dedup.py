"""``ApprovalRepository.has_pending_exit_for_trade`` (WS-5 PR-C dedup).

The urgent-exit sweep calls this before raising a fresh exit card so a still-
open alert is not re-sent every tick. It must be PENDING-AWARE: an exit card
that EXPIRED or was DECIDED no longer counts as pending, so a legitimate re-
raise can flow on the next tick.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from iguanatrader.contexts.approval.models import ApprovalDecision, ApprovalRequest
from iguanatrader.contexts.approval.repository import ApprovalRepository
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from iguanatrader.shared.time import UTC
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    db_path = tmp_path / "pending_exit.db"
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


async def _seed_tenant(sf: async_sessionmaker[AsyncSession], tid: object) -> None:
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()


@pytest.mark.asyncio
async def test_open_exit_card_is_pending_and_scoped_by_trade(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    open_trade = uuid4()
    other_trade = uuid4()
    await _seed_tenant(sf, tid)

    async with with_tenant_context(tid), sf() as s:
        s.add(
            ApprovalRequest(
                id=uuid4(),
                tenant_id=tid,
                proposal_id=None,
                delivered_to_channels=["telegram"],
                timeout_seconds=1800,
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
                created_at=datetime.now(UTC),
                action_type="exit",
                trade_id=open_trade,
            )
        )
        await s.commit()

    async with with_tenant_context(tid), sf() as s:
        session_var.set(s)
        repo = ApprovalRepository()
        assert await repo.has_pending_exit_for_trade(open_trade) is True
        # A different trade has no open card.
        assert await repo.has_pending_exit_for_trade(other_trade) is False


@pytest.mark.asyncio
async def test_expired_exit_card_is_not_pending(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    trade = uuid4()
    await _seed_tenant(sf, tid)

    async with with_tenant_context(tid), sf() as s:
        s.add(
            ApprovalRequest(
                id=uuid4(),
                tenant_id=tid,
                proposal_id=None,
                delivered_to_channels=["telegram"],
                timeout_seconds=60,
                expires_at=datetime.now(UTC) - timedelta(seconds=5),  # already expired
                created_at=datetime.now(UTC) - timedelta(minutes=5),
                action_type="exit",
                trade_id=trade,
            )
        )
        await s.commit()

    async with with_tenant_context(tid), sf() as s:
        session_var.set(s)
        repo = ApprovalRepository()
        # Expired → re-raise is allowed on the next tick.
        assert await repo.has_pending_exit_for_trade(trade) is False


@pytest.mark.asyncio
async def test_decided_exit_card_is_not_pending(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    trade = uuid4()
    rid = uuid4()
    await _seed_tenant(sf, tid)

    async with with_tenant_context(tid), sf() as s:
        s.add(
            ApprovalRequest(
                id=rid,
                tenant_id=tid,
                proposal_id=None,
                delivered_to_channels=["telegram"],
                timeout_seconds=1800,
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
                created_at=datetime.now(UTC),
                action_type="exit",
                trade_id=trade,
            )
        )
        await s.flush()
        s.add(
            ApprovalDecision(
                id=uuid4(),
                tenant_id=tid,
                request_id=rid,
                outcome="rejected",
                decided_via_channel="telegram",
                decided_by_user_id=None,
                decided_by_sender_id=None,
                latency_ms=10,
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()

    async with with_tenant_context(tid), sf() as s:
        session_var.set(s)
        repo = ApprovalRepository()
        # Already answered → not pending; the position is resolved.
        assert await repo.has_pending_exit_for_trade(trade) is False
