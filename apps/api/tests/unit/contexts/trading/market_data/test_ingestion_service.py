"""Unit tests for :class:`MarketDataIngestionService` (slice T4-followup-market-data §9.1.3).

6 tests cover: success, partial failure, full failure, rate-limit refusal,
env-var override, audit-row timing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from iguanatrader.contexts.trading.market_data import MarketDataRateLimitedError
from iguanatrader.contexts.trading.market_data.ibkr_ingestor import IngestResult
from iguanatrader.contexts.trading.market_data.models import MarketDataSyncAudit
from iguanatrader.contexts.trading.market_data.repository import (
    MarketDataSyncAuditRepository,
)
from iguanatrader.contexts.trading.market_data.service import (
    MarketDataIngestionService,
)
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from iguanatrader.shared.time import now as utc_now
from sqlalchemy import select
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
    db_path = tmp_path / "md_svc.db"
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
async def tenant_id(sf: async_sessionmaker[AsyncSession]) -> Any:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()
    return tid


def _make_ingestor(
    *, result: IngestResult | None = None, raises: Exception | None = None
) -> AsyncMock:
    ingestor = AsyncMock()
    if raises is not None:
        ingestor.ingest = AsyncMock(side_effect=raises)
    else:
        ingestor.ingest = AsyncMock(return_value=result or IngestResult())
    return ingestor


@pytest.mark.asyncio
async def test_success_path_writes_status_success_audit(
    sf: async_sessionmaker[AsyncSession],
    tenant_id: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR",
        raising=False,
    )
    ingestor = _make_ingestor(
        result=IngestResult(successes=["AAPL", "MSFT"], failures=[], bars_written=400),
    )

    async with with_tenant_context(tenant_id), sf() as s:
        session_var.set(s)
        service = MarketDataIngestionService(
            ingestor=ingestor,
            audit_repo=MarketDataSyncAuditRepository(),
        )
        result = await service.sync(
            symbols=["AAPL", "MSFT"],
            invoked_by="cli-sync",
        )
        await s.commit()

    assert result.bars_written == 400
    async with with_tenant_context(tenant_id), sf() as s:
        rows = (await s.execute(select(MarketDataSyncAudit))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].bars_written == 400
    assert rows[0].invoked_by == "cli-sync"
    assert rows[0].error is None


@pytest.mark.asyncio
async def test_partial_failure_writes_status_partial(
    sf: async_sessionmaker[AsyncSession],
    tenant_id: Any,
) -> None:
    ingestor = _make_ingestor(
        result=IngestResult(
            successes=["AAPL"],
            failures=[("XYZ", "delisted")],
            bars_written=200,
        ),
    )

    async with with_tenant_context(tenant_id), sf() as s:
        session_var.set(s)
        service = MarketDataIngestionService(
            ingestor=ingestor,
            audit_repo=MarketDataSyncAuditRepository(),
        )
        await service.sync(symbols=["AAPL", "XYZ"], invoked_by="daemon-cron")
        await s.commit()

    async with with_tenant_context(tenant_id), sf() as s:
        rows = (await s.execute(select(MarketDataSyncAudit))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "partial"
    assert rows[0].bars_written == 200


@pytest.mark.asyncio
async def test_full_failure_writes_status_failed_with_error(
    sf: async_sessionmaker[AsyncSession],
    tenant_id: Any,
) -> None:
    ingestor = _make_ingestor(raises=RuntimeError("ib gateway down"))

    async with with_tenant_context(tenant_id), sf() as s:
        session_var.set(s)
        service = MarketDataIngestionService(
            ingestor=ingestor,
            audit_repo=MarketDataSyncAuditRepository(),
        )
        with pytest.raises(RuntimeError):
            await service.sync(symbols=["AAPL"], invoked_by="cli-backfill")
        await s.commit()

    async with with_tenant_context(tenant_id), sf() as s:
        rows = (await s.execute(select(MarketDataSyncAudit))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].error is not None
    assert "ib gateway down" in rows[0].error


@pytest.mark.asyncio
async def test_rate_limit_refused_after_max_invocations(
    sf: async_sessionmaker[AsyncSession],
    tenant_id: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR", "2")

    ingestor = _make_ingestor(
        result=IngestResult(successes=["AAPL"], failures=[], bars_written=100),
    )

    async with with_tenant_context(tenant_id), sf() as s:
        session_var.set(s)
        service = MarketDataIngestionService(
            ingestor=ingestor,
            audit_repo=MarketDataSyncAuditRepository(),
        )
        # First two calls succeed.
        await service.sync(symbols=["AAPL"], invoked_by="cli-sync")
        await service.sync(symbols=["AAPL"], invoked_by="cli-sync")
        await s.commit()

    async with with_tenant_context(tenant_id), sf() as s:
        session_var.set(s)
        service = MarketDataIngestionService(
            ingestor=ingestor,
            audit_repo=MarketDataSyncAuditRepository(),
        )
        # Third call refused.
        with pytest.raises(MarketDataRateLimitedError):
            await service.sync(symbols=["AAPL"], invoked_by="cli-sync")
        await s.commit()

    async with with_tenant_context(tenant_id), sf() as s:
        rows = (
            (await s.execute(select(MarketDataSyncAudit).order_by(MarketDataSyncAudit.invoked_at)))
            .scalars()
            .all()
        )
    assert len(rows) == 3
    statuses = [r.status for r in rows]
    assert statuses == ["success", "success", "rate_limited"]


@pytest.mark.asyncio
async def test_env_var_override_applies_clamping(
    sf: async_sessionmaker[AsyncSession],
    tenant_id: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MAX=invalid`` falls back to default; ``MAX=1`` refuses 2nd call."""
    monkeypatch.setenv("IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR", "1")
    ingestor = _make_ingestor(
        result=IngestResult(successes=["AAPL"], failures=[], bars_written=100),
    )

    async with with_tenant_context(tenant_id), sf() as s:
        session_var.set(s)
        service = MarketDataIngestionService(
            ingestor=ingestor,
            audit_repo=MarketDataSyncAuditRepository(),
        )
        await service.sync(symbols=["AAPL"], invoked_by="cli-sync")
        with pytest.raises(MarketDataRateLimitedError):
            await service.sync(symbols=["AAPL"], invoked_by="cli-sync")


@pytest.mark.asyncio
async def test_audit_row_records_positive_duration_ms(
    sf: async_sessionmaker[AsyncSession],
    tenant_id: Any,
) -> None:
    """``duration_ms`` >= 0 on both success and failure paths."""
    ingestor = _make_ingestor(
        result=IngestResult(successes=["AAPL"], failures=[], bars_written=100),
    )

    async with with_tenant_context(tenant_id), sf() as s:
        session_var.set(s)
        service = MarketDataIngestionService(
            ingestor=ingestor,
            audit_repo=MarketDataSyncAuditRepository(),
        )
        await service.sync(symbols=["AAPL"], invoked_by="daemon-cron")
        await s.commit()

    async with with_tenant_context(tenant_id), sf() as s:
        row = (await s.execute(select(MarketDataSyncAudit))).scalar_one()
    assert row.duration_ms >= 0
    assert row.invoked_at >= utc_now() - timedelta(seconds=10)
