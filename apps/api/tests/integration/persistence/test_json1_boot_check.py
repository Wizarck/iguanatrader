"""SQLite JSON1 boot verification — happy path + missing-extension remediation."""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from typing import Any

import pytest
from iguanatrader.persistence import engine_factory, verify_json1_extension
from iguanatrader.persistence.errors import JSON1NotAvailableError
from sqlalchemy.exc import OperationalError


@dataclass
class _FakeDialect:
    name: str


class _FakeResult:
    def __init__(self, value: str | None = None) -> None:
        self._value = value

    def scalar_one(self) -> str | None:
        return self._value


class _FakeConn:
    """Async context manager simulating engine.connect()."""

    def __init__(self, *, raises: BaseException | None = None, value: str | None = "{}") -> None:
        self._raises = raises
        self._value = value
        self.execute_calls: list[tuple[Any, ...]] = []

    async def execute(self, *args: Any, **kwargs: Any) -> _FakeResult:
        self.execute_calls.append(args)
        if self._raises is not None:
            raise self._raises
        return _FakeResult(self._value)

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


class _FakeEngine:
    """Minimal AsyncEngine stand-in: dialect + connect()."""

    def __init__(self, *, dialect_name: str = "sqlite", conn: _FakeConn | None = None) -> None:
        self.dialect = _FakeDialect(name=dialect_name)
        self._conn = conn or _FakeConn()
        self.connect_calls = 0

    def connect(self) -> _FakeConn:
        self.connect_calls += 1
        return self._conn


@pytest.mark.asyncio
async def test_verify_json1_passes_on_python_311_plus() -> None:
    """Happy path on the official Python 3.11+ build with bundled SQLite >=3.38."""
    engine = engine_factory("sqlite+aiosqlite:///:memory:")
    try:
        await verify_json1_extension(engine)  # MUST NOT raise.
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_verify_json1_no_op_for_non_sqlite_dialects() -> None:
    """Postgres / MySQL have native JSONB; verify_json1 is a no-op."""
    fake_engine = _FakeEngine(dialect_name="postgresql")
    await verify_json1_extension(fake_engine)  # type: ignore[arg-type]
    assert fake_engine.connect_calls == 0


@pytest.mark.asyncio
async def test_verify_json1_raises_with_remediation_on_operationalerror() -> None:
    """Missing JSON1 → JSON1NotAvailableError with remediation message."""
    fake_conn = _FakeConn(
        raises=OperationalError("no such function: json", None, Exception("missing"))
    )
    fake_engine = _FakeEngine(dialect_name="sqlite", conn=fake_conn)

    with pytest.raises(JSON1NotAvailableError) as exc_info:
        await verify_json1_extension(fake_engine)  # type: ignore[arg-type]

    msg = str(exc_info.value)
    assert "Python" in msg
    assert sys.version.split()[0] in msg
    assert sqlite3.sqlite_version in msg
    assert "--enable-loadable-sqlite-extensions" in msg


@pytest.mark.asyncio
async def test_verify_json1_raises_on_unexpected_value() -> None:
    """JSON1 returned wrong value → JSON1NotAvailableError with the unexpected value."""
    fake_conn = _FakeConn(value="[broken]")
    fake_engine = _FakeEngine(dialect_name="sqlite", conn=fake_conn)

    with pytest.raises(JSON1NotAvailableError, match="\\[broken\\]"):
        await verify_json1_extension(fake_engine)  # type: ignore[arg-type]
