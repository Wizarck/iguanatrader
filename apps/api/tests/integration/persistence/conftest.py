"""Integration test fixtures for persistence layer.

Each test function gets:
- A fresh on-disk SQLite engine + ``async_sessionmaker`` (tmp_path, auto-cleaned).
- All tenant + append-only listeners registered (and unregistered after the test).
- An empty schema with the test models created from ``Base.metadata``.

The tests in this directory define their own throwaway ORM models per file so
that they don't depend on any future bounded-context tables shipping (those
land in slices T1/R1+). The models inherit from ``Base`` so they pick up the
naming convention + class attributes (``__tenant_scoped__``, etc.).
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from iguanatrader.persistence import (
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

# Hypothesis + asyncio.run on Windows leaks file descriptors under
# filterwarnings=["error"] when the default ProactorEventLoop is used (slice 2
# gotcha). The selector loop is the safe choice for SQLite-on-aiosqlite tests.
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """Per-test on-disk SQLite (in-memory + WAL + multiple sessions = flaky)."""
    db_path = tmp_path / "ig_test.db"
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


@pytest.fixture
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    eng = engine_factory(db_url)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session_factory_fx(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory with an empty schema created from ``Base.metadata``."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield session_factory(engine)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def _register_listeners() -> Iterator[None]:
    """Register tenant + append-only listeners for the duration of the test."""
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()
