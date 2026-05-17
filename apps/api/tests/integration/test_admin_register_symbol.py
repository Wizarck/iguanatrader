"""Integration test for ``iguanatrader admin register-symbol``.

Asserts:

1. Happy path — fresh DB with a tenant → ``symbol_universe`` +
   ``watchlist_configs`` rows inserted for the tenant.
2. Unknown tenant slug exits non-zero with a helpful message.
3. Re-registering the same ``(symbol, exchange)`` exits non-zero
   (unique constraint on ``symbol_universe``).
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from iguanatrader.cli.admin import app as admin_app
from iguanatrader.contexts.research.models import SymbolUniverse, WatchlistConfig
from iguanatrader.persistence import (
    Tenant,
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
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'ig_regsym_test.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'ig_regsym_test.db').as_posix()}"


@pytest.fixture
async def schema_session_factory(
    engine_with_schema: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine_with_schema)


def _run_admin(
    db_url: str,
    *args: str,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, str]:
    monkeypatch.setenv("IGUANA_DATABASE_URL", db_url)
    runner = CliRunner()
    result = runner.invoke(admin_app, list(args))
    output = result.output or ""
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        import traceback

        output += "\n\n--- exception ---\n" + "".join(
            traceback.format_exception(
                type(result.exception), result.exception, result.exception.__traceback__
            )
        )
    return result.exit_code, output


async def _bootstrap(db_url: str, slug: str, monkeypatch: pytest.MonkeyPatch) -> None:
    code, output = _run_admin(
        db_url,
        "bootstrap-tenant",
        slug,
        "--email",
        f"{slug}@example.com",
        "--password",
        "p1",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output


@pytest.mark.asyncio
async def test_register_symbol_inserts_universe_and_watchlist(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _bootstrap(db_url, "arturo-trading", monkeypatch)

    code, output = _run_admin(
        db_url,
        "register-symbol",
        "NVDA",
        "--tenant",
        "arturo-trading",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output
    assert "OK" in output
    assert "symbol=NVDA" in output

    async with schema_session_factory() as session:
        tenant = (
            (await session.execute(select(Tenant).where(Tenant.name == "arturo-trading")))
            .scalars()
            .first()
        )
        assert tenant is not None
        su = (
            (
                await session.execute(
                    select(SymbolUniverse).where(SymbolUniverse.tenant_id == tenant.id)
                )
            )
            .scalars()
            .first()
        )
        assert su is not None
        assert su.symbol == "NVDA"
        assert su.exchange == "NASDAQ"
        wc = (
            (
                await session.execute(
                    select(WatchlistConfig).where(WatchlistConfig.symbol_universe_id == su.id)
                )
            )
            .scalars()
            .first()
        )
        assert wc is not None
        assert wc.tier == "primary"
        assert wc.methodology == "three_pillar"
        assert wc.brief_refresh_schedule == "manual"


@pytest.mark.asyncio
async def test_register_symbol_unknown_tenant_exits_non_zero(
    db_url: str,
    engine_with_schema: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, output = _run_admin(
        db_url,
        "register-symbol",
        "NVDA",
        "--tenant",
        "does-not-exist",
        monkeypatch=monkeypatch,
    )
    assert code != 0
    assert "not found" in output


@pytest.mark.asyncio
async def test_register_symbol_duplicate_exits_non_zero(
    db_url: str,
    engine_with_schema: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _bootstrap(db_url, "dup-tenant", monkeypatch)

    code1, _ = _run_admin(
        db_url,
        "register-symbol",
        "AAPL",
        "--tenant",
        "dup-tenant",
        monkeypatch=monkeypatch,
    )
    assert code1 == 0

    code2, output2 = _run_admin(
        db_url,
        "register-symbol",
        "AAPL",
        "--tenant",
        "dup-tenant",
        monkeypatch=monkeypatch,
    )
    assert code2 != 0
    assert "already registered" in output2
