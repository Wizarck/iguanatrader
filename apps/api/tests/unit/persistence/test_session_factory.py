"""Session factory + SQLite PRAGMA listener wiring."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from iguanatrader.persistence.session import engine_factory, session_factory


@pytest.mark.asyncio
async def test_engine_factory_returns_async_engine_with_sqlite_pragmas() -> None:
    engine = engine_factory("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            fk = (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar_one()
            jm = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
            bt = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()
        assert fk == 1
        assert jm.lower() in {"wal", "memory"}
        assert bt == 30000
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_factory_expire_on_commit_false() -> None:
    engine = engine_factory("sqlite+aiosqlite:///:memory:")
    try:
        factory = session_factory(engine)
        assert isinstance(factory, async_sessionmaker)
        async with factory() as session:
            assert isinstance(session, AsyncSession)
            assert session.sync_session.expire_on_commit is False
            result = (await session.execute(text("SELECT 1"))).scalar_one()
            assert result == 1
    finally:
        await engine.dispose()
