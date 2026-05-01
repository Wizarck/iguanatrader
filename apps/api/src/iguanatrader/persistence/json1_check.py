"""SQLite JSON1 extension boot verification.

Per design D7 (slice 3): the application cannot start without JSON1 (the
``feature_flags`` column relies on JSON queries). Failing fast at boot with an
explicit remediation message saves the operator a debugging session compared
to an opaque ``OperationalError: no such function: json`` deep into operation.
"""

from __future__ import annotations

import sqlite3
import sys

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from iguanatrader.persistence.errors import JSON1NotAvailableError

_REMEDIATION = (
    "Two supported remediation paths: "
    "(a) install Python 3.11+ official build with bundled SQLite >=3.38; "
    "(b) recompile your Python with --enable-loadable-sqlite-extensions and "
    "load the JSON1 module."
)


async def verify_json1_extension(engine: AsyncEngine) -> None:
    """Verify the SQLite JSON1 extension is available on this engine's connections.

    For non-SQLite engines (Postgres, MySQL) this is a no-op — JSONB is native.

    On SQLite engines, opens a connection and runs ``SELECT json('{}')``. If the
    call fails with :class:`OperationalError` (extension missing) or returns an
    unexpected value, raises :class:`JSON1NotAvailableError` whose message names
    the detected Python and SQLite versions and the two supported remediation
    paths.
    """
    if engine.dialect.name != "sqlite":
        return

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT json('{}')"))
            value = result.scalar_one()
    except OperationalError as exc:
        raise JSON1NotAvailableError(
            f"SQLite JSON1 extension not available "
            f"(Python {sys.version.split()[0]}, "
            f"SQLite {sqlite3.sqlite_version}): {exc}. "
            f"{_REMEDIATION}"
        ) from exc

    if value != "{}":
        raise JSON1NotAvailableError(
            f"SQLite JSON1 returned unexpected value {value!r} "
            f"(expected '{{}}'); Python {sys.version.split()[0]}, "
            f"SQLite {sqlite3.sqlite_version}. "
            f"{_REMEDIATION}"
        )


__all__ = ["verify_json1_extension"]
