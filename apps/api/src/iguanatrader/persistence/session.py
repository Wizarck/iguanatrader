"""Async engine + session factory.

Pure factories — no module-level state. The SQLite PRAGMAs (``WAL``,
``foreign_keys=ON``, ``busy_timeout=30000``) are wired via a connect listener
so they apply to every connection, not just the first one in the pool.

Per design D5 (slice 3): ``expire_on_commit=False`` because in async code,
attribute access after commit triggers an implicit refresh which is async —
easy to forget the ``await``. With ``expire_on_commit=False`` the commit
returns and instances stay usable; the trade-off (stale data after commit
if another writer touched the row) is irrelevant in MVP single-writer.

Audit #29 — ``sqlite_begin_immediate``: opt-in ``BEGIN IMMEDIATE`` transaction
mode for engines that run several concurrent write units of work against the
same SQLite file (the trading daemon: heartbeat every 10s, stop-hit sweep
every minute, propose ticks, bus deliveries — each a fresh per-unit session).
pysqlite opens transactions ``DEFERRED`` and lazily, so a unit that reads then
writes takes a SHARED lock on the SELECT and tries to upgrade to RESERVED on
the INSERT; two such units overlapping deadlock on the upgrade and SQLite
returns ``SQLITE_BUSY`` *immediately* — ``busy_timeout`` cannot break a
deadlock, so the periodic "database is locked" survived WAL + a 30s timeout.
``BEGIN IMMEDIATE`` takes the RESERVED write lock up front, so concurrent
writers queue on ``busy_timeout`` instead of deadlocking. Left off by default
(the API process serves concurrent reads that WAL keeps lock-free with the
``DEFERRED`` default); the daemon opts in.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Apply SQLite PRAGMAs on every new connection.

    ``foreign_keys = ON`` — SQLite ignores FK constraints by default. Without
    this, the FKs declared in the schema are decorative.

    ``journal_mode = WAL`` — Write-Ahead Logging permits concurrent readers
    while a writer is active; the standard ROLLBACK journal blocks all readers
    during writes. WAL is the standard choice for any non-trivial SQLite app.

    ``busy_timeout = 30000`` — milliseconds the driver waits when the database
    file is locked. The default (0) returns ``SQLITE_BUSY`` immediately, which
    surfaces as a confusing ``OperationalError`` under normal contention. 30s
    is well above any reasonable lock-hold time in a single-writer MVP.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA busy_timeout = 30000")
    finally:
        cursor.close()


def _sqlite_disable_implicit_begin(dbapi_connection: Any, connection_record: Any) -> None:
    """Hand transaction control to SQLAlchemy so we can emit ``BEGIN IMMEDIATE``.

    Setting the DBAPI ``isolation_level`` to ``None`` disables pysqlite's
    implicit, lazy ``BEGIN`` (DEFERRED). SQLAlchemy then opens each transaction
    explicitly via the ``begin`` event (:func:`_sqlite_begin_immediate`). The
    connect-time PRAGMAs run fine in the resulting autocommit mode.
    """
    dbapi_connection.isolation_level = None


def _sqlite_begin_immediate(conn: Any) -> None:
    """Emit ``BEGIN IMMEDIATE`` at the start of every transaction (audit #29).

    Acquires the RESERVED write lock up front so two concurrent write units of
    work queue on ``busy_timeout`` rather than deadlocking on a DEFERRED
    read→write lock upgrade (which ``busy_timeout`` cannot resolve).
    """
    conn.exec_driver_sql("BEGIN IMMEDIATE")


def engine_factory(
    url: str,
    *,
    echo: bool = False,
    sqlite_begin_immediate: bool = False,
) -> AsyncEngine:
    """Build an :class:`AsyncEngine` from a database URL.

    Registers the SQLite PRAGMA listener only when the URL identifies SQLite
    (so passing a Postgres URL in v1.5 won't trigger a no-op listener).

    ``sqlite_begin_immediate`` (SQLite only) switches transactions to
    ``BEGIN IMMEDIATE`` — see the module docstring (audit #29). The trading
    daemon passes it; the API leaves it off to keep concurrent reads lock-free.
    """
    engine = create_async_engine(url, echo=echo)
    if url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
        if sqlite_begin_immediate:
            event.listen(
                engine.sync_engine, "connect", _sqlite_disable_implicit_begin
            )
            event.listen(engine.sync_engine, "begin", _sqlite_begin_immediate)
    return engine


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build an :class:`async_sessionmaker` bound to ``engine``.

    Returns a callable. Call it (without arguments) to obtain a fresh
    :class:`AsyncSession` per unit of work — typically once per request, once
    per CLI command, or once per scheduler tick.
    """
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


__all__ = ["AsyncEngine", "AsyncSession", "engine_factory", "session_factory"]


# Suppress "unused import" — :class:`Engine` is exported transitively by
# :mod:`sqlalchemy.ext.asyncio.AsyncEngine.sync_engine`; type checkers that
# follow ``sync_engine`` need the symbol resolvable at the import site.
_: Any = Engine
