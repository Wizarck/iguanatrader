"""Append-only invariant — UPDATE/DELETE on approval tables raise.

Per slice P1 task 6.9 + design D5. Exercises the slice-3 L1 listener
(``before_flush``) — directly attempt an ORM UPDATE on a seeded row
and assert :class:`AppendOnlyViolationError`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.approval.models import (
    ApprovalDecision,
    ApprovalRequest,
)
from iguanatrader.contexts.trading.models import StrategyConfig, TradeProposal
from iguanatrader.persistence import (
    AppendOnlyViolationError,
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import with_tenant_context
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
    db_path = tmp_path / "append_only.db"
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


async def _seed_proposal_chain(
    sf: async_sessionmaker[AsyncSession],
    tid: UUID,
) -> UUID:
    """Seed StrategyConfig + TradeProposal so ApprovalRequest's FK resolves.

    Flush per-add to sidestep SQLAlchemy 2.x INSERTMANYVALUES race on
    aiosqlite (per PR #184 docs). Returns the proposal_id.
    """
    sc_id = uuid4()
    proposal_id = uuid4()
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
        await s.commit()
    return proposal_id


@pytest.mark.asyncio
async def test_update_on_approval_request_raises(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    rid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()
    proposal_id = await _seed_proposal_chain(sf, tid)
    async with with_tenant_context(tid), sf() as s:
        s.add(
            ApprovalRequest(
                id=rid,
                tenant_id=tid,
                proposal_id=proposal_id,
                delivered_to_channels=["telegram"],
                timeout_seconds=60,
                expires_at=datetime.now(UTC) + timedelta(seconds=60),
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        instance = await s.get(ApprovalRequest, rid)
        assert instance is not None
        instance.timeout_seconds = 999
        with pytest.raises(AppendOnlyViolationError):
            await s.flush()


@pytest.mark.asyncio
async def test_update_on_approval_decision_raises(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    rid = uuid4()
    did = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()
    proposal_id = await _seed_proposal_chain(sf, tid)
    async with with_tenant_context(tid), sf() as s:
        s.add(
            ApprovalRequest(
                id=rid,
                tenant_id=tid,
                proposal_id=proposal_id,
                delivered_to_channels=["telegram"],
                timeout_seconds=60,
                expires_at=datetime.now(UTC) + timedelta(seconds=60),
                created_at=datetime.now(UTC),
            )
        )
        await s.flush()
        s.add(
            ApprovalDecision(
                id=did,
                tenant_id=tid,
                request_id=rid,
                outcome="granted",
                decided_via_channel="telegram",
                latency_ms=100,
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        instance = await s.get(ApprovalDecision, did)
        assert instance is not None
        instance.outcome = "rejected"
        with pytest.raises(AppendOnlyViolationError):
            await s.flush()
