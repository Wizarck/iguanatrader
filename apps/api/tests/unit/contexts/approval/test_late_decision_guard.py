"""#30: ``record_decision`` rejects human decisions that land after
``expires_at`` with :class:`ApprovalExpiredError` (HTTP 410).

Without the guard a ``granted``/``rejected`` arriving at the same instant
the timeout sweeper fires would race it: both persist a decision and the
bus emits BOTH the approve/reject event AND ``approval_timeout`` for the
same proposal (double execution / split state). The sweeper's own timeout
path calls the repository directly, so it is unaffected.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.approval.errors import ApprovalExpiredError
from iguanatrader.contexts.approval.models import ApprovalRequest
from iguanatrader.contexts.approval.repository import ApprovalRepository
from iguanatrader.contexts.approval.service import ApprovalService
from iguanatrader.contexts.trading.models import StrategyConfig, TradeProposal
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from iguanatrader.shared.messagebus import MessageBus
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
    db_path = tmp_path / "late_decision.db"
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


async def _seed_request(
    sf: async_sessionmaker[AsyncSession],
    *,
    tid: UUID,
    rid: UUID,
    expires_at: datetime,
) -> None:
    sc_id = uuid4()
    proposal_id = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            StrategyConfig(
                id=sc_id,
                tenant_id=tid,
                strategy_kind="donchian_atr",
                symbol="AAPL",
                params={"lookback": 20},
                enabled=True,
            )
        )
        await s.flush()
        s.add(
            TradeProposal(
                id=proposal_id,
                tenant_id=tid,
                strategy_config_id=sc_id,
                research_brief_id=None,
                correlation_id=uuid4(),
                symbol="AAPL",
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("100"),
                stop_price=Decimal("90"),
                reasoning={"why": "test"},
                mode="paper",
            )
        )
        await s.flush()
        s.add(
            ApprovalRequest(
                id=rid,
                tenant_id=tid,
                proposal_id=proposal_id,
                delivered_to_channels=["telegram"],
                timeout_seconds=60,
                expires_at=expires_at,
                created_at=expires_at - timedelta(seconds=60),
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_record_decision_rejects_decision_after_expiry(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid, rid = uuid4(), uuid4()
    # Expired five seconds ago.
    await _seed_request(sf, tid=tid, rid=rid, expires_at=datetime.now(UTC) - timedelta(seconds=5))

    bus = MessageBus()
    try:
        async with with_tenant_context(tid), sf() as session:
            session_var.set(session)
            service = ApprovalService(repository=ApprovalRepository(), message_bus=bus)
            with pytest.raises(ApprovalExpiredError):
                await service.record_decision(
                    request_id=rid,
                    outcome="granted",
                    decided_via_channel="telegram",
                    decided_by_user_id=None,
                )
    finally:
        await bus.aclose()


@pytest.mark.asyncio
async def test_record_decision_accepts_decision_within_window(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid, rid = uuid4(), uuid4()
    # Still open: expires a minute from now.
    await _seed_request(sf, tid=tid, rid=rid, expires_at=datetime.now(UTC) + timedelta(seconds=60))

    bus = MessageBus()
    try:
        async with with_tenant_context(tid), sf() as session:
            session_var.set(session)
            service = ApprovalService(repository=ApprovalRepository(), message_bus=bus)
            decision = await service.record_decision(
                request_id=rid,
                outcome="granted",
                decided_via_channel="telegram",
                decided_by_user_id=None,
            )
            await session.commit()
        assert decision.outcome == "granted"
    finally:
        await bus.aclose()
