"""#36: ``risk_evaluations.cap_type_breached`` CHECK accepts the v1.5 caps.

``stoploss_guard`` and ``cooldown_period`` are real protections in the
engine pipeline; before the CHECK was widened, persisting an evaluation
breached by either raised an IntegrityError (SQLite enforces CHECKs), so
the engine crashed the moment those caps were configured.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from iguanatrader.contexts.risk.orm import RiskEvaluationORM
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
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
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'rc.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


@pytest.mark.parametrize("cap_type", ["stoploss_guard", "cooldown_period"])
@pytest.mark.asyncio
async def test_risk_evaluation_accepts_v15_cap_types(
    sf: async_sessionmaker[AsyncSession],
    cap_type: str,
) -> None:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()

    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        session.add(
            RiskEvaluationORM(
                id=uuid4(),
                tenant_id=tid,
                proposal_id=uuid4(),
                outcome="reject",
                cap_type_breached=cap_type,
                current_pct=Decimal("1.000000"),
                state_snapshot={},
                created_at=datetime.now(UTC),
            )
        )
        # Must NOT raise IntegrityError on the CHECK.
        await session.commit()
