"""Timeout sweeper — pre-seeded expired request → timeout decision + event.

Per slice P1 task 6.10 + spec ``approval`` Requirement 5 scenario
"Timeout sweeper records system-decided outcome".
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from iguanatrader.contexts.approval.events import ApprovalProposalTimedOut
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
from iguanatrader.shared.contextvars import (
    session_var,
    with_tenant_context,
)
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
    db_path = tmp_path / "sweeper.db"
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


@pytest.mark.asyncio
async def test_sweep_records_timeout_and_emits_event(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    rid = uuid4()
    proposal_id = uuid4()
    sc_id = uuid4()
    expires_at = datetime.now(UTC) - timedelta(seconds=5)
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()
    # Seed StrategyConfig + TradeProposal so the ApprovalRequest's
    # proposal_id FK to trade_proposals.id resolves. Flush per-add to
    # sidestep SQLAlchemy 2.x INSERTMANYVALUES race on aiosqlite (see
    # PR #184 docs).
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

    bus = MessageBus()
    received: list[ApprovalProposalTimedOut] = []

    async def _on_timed_out(ev: ApprovalProposalTimedOut) -> None:
        received.append(ev)

    sub = bus.subscribe(ApprovalProposalTimedOut, _on_timed_out)
    try:
        async with with_tenant_context(tid), sf() as session:
            session_var.set(session)
            repo = ApprovalRepository()
            service = ApprovalService(repository=repo, message_bus=bus)
            decisions = await service.sweep_expired_requests(
                now=datetime.now(UTC) + timedelta(seconds=1)
            )
            await session.commit()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    finally:
        await bus.unsubscribe(sub)
        await bus.aclose()

    assert len(decisions) == 1
    assert decisions[0].outcome == "timeout"
    assert decisions[0].decided_via_channel == "timeout"
    assert decisions[0].decided_by_user_id is None
    assert decisions[0].decided_by_sender_id is None
    assert len(received) == 1
    assert received[0].proposal_id == proposal_id
