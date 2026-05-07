"""Unit tests for the async :func:`_make_strategy_resolver` (slice T4-followup-market-data §9.1.4).

Verifies that the closure produced by ``_make_strategy_resolver`` resolves a
``UUID → StrategyPort`` via a session-scoped repository lookup, and raises
``LookupError`` on a missing config row.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from iguanatrader.cli.trading import _make_strategy_resolver
from iguanatrader.contexts.trading.models import StrategyConfig
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import with_tenant_context
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
    db_path = tmp_path / "resolver.db"
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


@pytest.mark.asyncio
async def test_resolver_returns_strategy_for_existing_config(
    sf: async_sessionmaker[AsyncSession],
    tenant_id: Any,
) -> None:
    config_id = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            StrategyConfig(
                id=config_id,
                tenant_id=tenant_id,
                strategy_kind="donchian_atr",
                symbol="AAPL",
                params={
                    "channel_lookback": 20,
                    "atr_lookback": 14,
                    "atr_stop_multiplier": "2",
                },
                enabled=True,
                version=1,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await s.commit()

    resolver = _make_strategy_resolver(session_factory=sf)

    async with with_tenant_context(tenant_id):
        strategy = await resolver(config_id)

    assert strategy is not None
    assert strategy.name() == "donchian_atr"


@pytest.mark.asyncio
async def test_resolver_raises_lookup_error_on_missing_config(
    sf: async_sessionmaker[AsyncSession],
    tenant_id: Any,
) -> None:
    resolver = _make_strategy_resolver(session_factory=sf)
    bogus_id = uuid4()

    async with with_tenant_context(tenant_id):
        with pytest.raises(LookupError) as exc_info:
            await resolver(bogus_id)

    assert str(bogus_id) in str(exc_info.value)
