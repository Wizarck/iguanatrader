"""Session factory + SQLite PRAGMA listener wiring."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
from iguanatrader.persistence.session import engine_factory, session_factory
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _file_sqlite_url() -> str:
    """A throwaway file-backed SQLite URL.

    A file (not ``:memory:``) is required for the BEGIN-mode tests: in-memory
    databases are per-connection, so cross-connection locking never engages.
    """
    path = Path(tempfile.mkdtemp()) / "t.db"
    return f"sqlite+aiosqlite:///{path.as_posix()}"


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


@pytest.mark.asyncio
async def test_begin_immediate_emitted_only_when_opted_in() -> None:
    """``sqlite_begin_immediate=True`` makes transactions open with BEGIN IMMEDIATE.

    Audit #29: acquiring the write lock at transaction start avoids the DEFERRED
    read→write upgrade deadlock that busy_timeout cannot break. The default must
    NOT emit it (the API keeps reads lock-free under WAL).
    """

    async def collect_begin(*, immediate: bool) -> list[str]:
        engine = engine_factory(_file_sqlite_url(), sqlite_begin_immediate=immediate)
        seen: list[str] = []

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def _capture(conn, cursor, statement, params, context, executemany):  # type: ignore[no-untyped-def]
            seen.append(statement.strip().upper())

        try:
            factory = session_factory(engine)
            async with factory() as session:
                await session.execute(
                    text("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)")
                )
                await session.execute(text("INSERT INTO t (v) VALUES (1)"))
                await session.commit()
        finally:
            await engine.dispose()
        return seen

    immediate = await collect_begin(immediate=True)
    deferred = await collect_begin(immediate=False)

    assert "BEGIN IMMEDIATE" in immediate
    assert "BEGIN IMMEDIATE" not in deferred


@pytest.mark.asyncio
async def test_begin_immediate_pragmas_still_apply() -> None:
    """Opting into BEGIN IMMEDIATE must not drop the WAL / busy_timeout PRAGMAs."""
    engine = engine_factory(_file_sqlite_url(), sqlite_begin_immediate=True)
    try:
        async with engine.connect() as conn:
            jm = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
            bt = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()
        assert jm.lower() == "wal"
        assert bt == 30000
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_begin_immediate_serializes_concurrent_write_units() -> None:
    """Concurrent read-then-write units of work all commit (no 'database is locked').

    Each coroutine reads then writes on its own session — the exact daemon shape
    (audit #29). With BEGIN IMMEDIATE they queue on busy_timeout rather than
    deadlocking on a lock upgrade.
    """
    url = _file_sqlite_url()
    engine = engine_factory(url, sqlite_begin_immediate=True)
    factory = session_factory(engine)
    try:
        async with factory() as session:
            await session.execute(
                text("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)")
            )
            await session.commit()

        async def unit(n: int) -> None:
            async with factory() as session:
                await session.execute(text("SELECT COUNT(*) FROM t"))
                await asyncio.sleep(0.02)  # widen the overlap window
                await session.execute(
                    text("INSERT INTO t (v) VALUES (:v)"), {"v": n}
                )
                await session.commit()

        await asyncio.gather(*(unit(i) for i in range(8)))

        async with factory() as session:
            count = (await session.execute(text("SELECT COUNT(*) FROM t"))).scalar_one()
        assert count == 8
    finally:
        await engine.dispose()
