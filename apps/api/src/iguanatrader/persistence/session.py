"""Async engine + session factory.

Pure factories — no module-level state. The SQLite PRAGMAs (``WAL``,
``foreign_keys=ON``, ``busy_timeout=30000``) are wired via a connect listener
so they apply to every connection, not just the first one in the pool.

Per design D5 (slice 3): ``expire_on_commit=False`` because in async code,
attribute access after commit triggers an implicit refresh which is async —
easy to forget the ``await``. With ``expire_on_commit=False`` the commit
returns and instances stay usable; the trade-off (stale data after commit
if another writer touched the row) is irrelevant in MVP single-writer.
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


def engine_factory(url: str, *, echo: bool = False) -> AsyncEngine:
    """Build an :class:`AsyncEngine` from a database URL.

    Registers the SQLite PRAGMA listener only when the URL identifies SQLite
    (so passing a Postgres URL in v1.5 won't trigger a no-op listener).

    ``pool_pre_ping`` is always on: a half-open connection handed back from the
    pool is detected + recycled before first use, instead of the next
    ``await session.execute(...)`` hanging on a dead socket. For Postgres
    (asyncpg) we additionally set ``command_timeout`` so a single statement
    parked on a server-side lock or stalled connection raises rather than
    blocking forever — the daemon cron sweeps share this engine, and one such
    hang silently froze every sweep on 2026-06-29 (see ``apscheduler_adapter``).
    """
    kwargs: dict[str, Any] = {"echo": echo, "pool_pre_ping": True}
    if url.startswith("postgresql"):
        kwargs["connect_args"] = {"command_timeout": 30}
    engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
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
