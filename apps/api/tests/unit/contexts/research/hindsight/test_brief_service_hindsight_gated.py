"""Direct unit tests for ``BriefService._maybe_recall_hindsight`` (slice R6).

The full ``refresh`` pipeline is integration-tested elsewhere (R5).
This module focuses on the recall-gating logic in isolation:

* ``hindsight is None`` -> returns [] without lookup.
* ``feature_flags.hindsight_recall_enabled`` falsy -> returns [].
* Flag truthy -> calls ``hindsight.recall`` and returns its result.
* Recall raises -> returns [] (graceful degradation).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from iguanatrader.contexts.research.hindsight import HindsightUnavailable
from iguanatrader.contexts.research.hindsight.in_memory import (
    InMemoryHindsightAdapter,
)
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.contexts.research.service import BriefService
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
    db_path = tmp_path / "ig_hindsight_gated.db"
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


def _make_service(
    *,
    hindsight: Any | None,
    repo: ResearchRepository,
) -> BriefService:
    return BriefService(
        repository=repo,
        composite_provider=AsyncMock(),
        synthesizer=AsyncMock(),
        audit_service=AsyncMock(),
        bus=None,
        default_model="x",
        hindsight=hindsight,
    )


@pytest.mark.asyncio
async def test_no_hindsight_returns_empty_list(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        repo = ResearchRepository()
        service = _make_service(hindsight=None, repo=repo)
        result = await service._maybe_recall_hindsight("AAPL")
    assert result == []


@pytest.mark.asyncio
async def test_flag_off_returns_empty_list(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    async with sf() as s:
        s.add(
            Tenant(
                id=tid,
                name="t",
                feature_flags={"hindsight_recall_enabled": False},
            )
        )
        await s.commit()
    hindsight = InMemoryHindsightAdapter(
        seed={f"iguanatrader-research-{tid}": ["should not be returned"]},
    )
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        repo = ResearchRepository()
        service = _make_service(hindsight=hindsight, repo=repo)
        result = await service._maybe_recall_hindsight("AAPL")
    assert result == []


@pytest.mark.asyncio
async def test_flag_on_calls_recall(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    async with sf() as s:
        s.add(
            Tenant(
                id=tid,
                name="t",
                feature_flags={"hindsight_recall_enabled": True},
            )
        )
        await s.commit()
    hindsight = InMemoryHindsightAdapter(
        seed={
            f"iguanatrader-research-{tid}": [
                "[brief_summary] AAPL recurring theme: services growth",
            ],
        },
    )
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        repo = ResearchRepository()
        service = _make_service(hindsight=hindsight, repo=repo)
        result = await service._maybe_recall_hindsight("AAPL")
    assert len(result) == 1
    assert "AAPL" in result[0]


@pytest.mark.asyncio
async def test_recall_raises_returns_empty_list(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    async with sf() as s:
        s.add(
            Tenant(
                id=tid,
                name="t",
                feature_flags={"hindsight_recall_enabled": True},
            )
        )
        await s.commit()
    failing = AsyncMock()
    failing.recall = AsyncMock(side_effect=HindsightUnavailable(detail="boom"))
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        repo = ResearchRepository()
        service = _make_service(hindsight=failing, repo=repo)
        # MUST NOT raise.
        result = await service._maybe_recall_hindsight("AAPL")
    assert result == []
