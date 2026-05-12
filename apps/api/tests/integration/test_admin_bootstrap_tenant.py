"""Integration test for ``iguanatrader admin bootstrap-tenant``.

Asserts:

1. Happy path — fresh DB → tenant + user rows inserted; password stored
   as Argon2id hash; user role is ``tenant_user``.
2. Duplicate slug without ``--force-reset`` exits non-zero.
3. ``--force-reset`` deletes the existing tenant + user, recreates fresh.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from iguanatrader.cli.admin import app as admin_app
from iguanatrader.persistence import (
    Tenant,
    User,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from typer.testing import CliRunner

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
async def engine_with_schema(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """Per-test on-disk SQLite + schema created from ``Base.metadata``."""
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'ig_bootstrap_test.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'ig_bootstrap_test.db').as_posix()}"


@pytest.fixture
async def schema_session_factory(
    engine_with_schema: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine_with_schema)


def _run_bootstrap(
    db_url: str,
    *args: str,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, str]:
    """Invoke the admin Typer app with the test DB URL injected via env."""
    monkeypatch.setenv("IGUANA_DATABASE_URL", db_url)
    runner = CliRunner()
    result = runner.invoke(admin_app, ["bootstrap-tenant", *args])
    return result.exit_code, (result.output or "")


@pytest.mark.asyncio
async def test_bootstrap_creates_tenant_and_user(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fixtures order: schema must exist before the CLI hits the DB.
    code, output = _run_bootstrap(
        db_url,
        "arturo-trading",
        "--email",
        "arturo@example.com",
        "--password",
        "horse-battery-staple-1",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output
    assert "OK" in output
    assert "tenant_id=" in output
    assert "user_id=" in output

    # Verify rows + Argon2id hash shape.
    async with schema_session_factory() as session:
        tenant_row = (
            (await session.execute(select(Tenant).where(Tenant.name == "arturo-trading")))
            .scalars()
            .first()
        )
        assert tenant_row is not None
        user_row = (
            (await session.execute(select(User).where(User.email == "arturo@example.com")))
            .scalars()
            .first()
        )
        assert user_row is not None
        assert user_row.role == "tenant_user"
        assert user_row.tenant_id == tenant_row.id
        # Argon2id encoded hash format: $argon2id$v=19$m=...$t=...$<salt>$<hash>.
        assert user_row.password_hash.startswith("$argon2")


@pytest.mark.asyncio
async def test_duplicate_slug_without_force_reset_exits_non_zero(
    db_url: str,
    engine_with_schema: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First bootstrap succeeds.
    code1, _ = _run_bootstrap(
        db_url,
        "dup-tenant",
        "--email",
        "first@example.com",
        "--password",
        "p1",
        monkeypatch=monkeypatch,
    )
    assert code1 == 0

    # Second bootstrap (same slug) fails without --force-reset.
    code2, output2 = _run_bootstrap(
        db_url,
        "dup-tenant",
        "--email",
        "second@example.com",
        "--password",
        "p2",
        monkeypatch=monkeypatch,
    )
    assert code2 != 0
    assert "already exists" in output2


@pytest.mark.asyncio
async def test_force_reset_replaces_existing_tenant(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code1, _ = _run_bootstrap(
        db_url,
        "reset-me",
        "--email",
        "before@example.com",
        "--password",
        "p1",
        monkeypatch=monkeypatch,
    )
    assert code1 == 0

    code2, output2 = _run_bootstrap(
        db_url,
        "reset-me",
        "--email",
        "after@example.com",
        "--password",
        "p2",
        "--force-reset",
        monkeypatch=monkeypatch,
    )
    assert code2 == 0, output2
    assert "--force-reset" in output2

    async with schema_session_factory() as session:
        before = (
            (await session.execute(select(User).where(User.email == "before@example.com")))
            .scalars()
            .first()
        )
        after = (
            (await session.execute(select(User).where(User.email == "after@example.com")))
            .scalars()
            .first()
        )
    assert before is None
    assert after is not None
