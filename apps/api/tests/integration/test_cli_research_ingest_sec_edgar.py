"""Integration test for ``iguanatrader research ingest sec-edgar``.

Asserts the CLI's argument parsing + control flow without hitting the
live SEC EDGAR endpoint. The adapter is monkeypatched to return a
fixed list of pre-built drafts so the test validates:

1. Happy path — drafts persist to ``research_facts`` with the resolved
   ``symbol_universe_id`` stamped on each row.
2. Unknown symbol — exits non-zero with a registration hint.
3. ``--since`` parses as ISO 8601 and is forwarded to the adapter.
4. Invalid ``--since`` value exits non-zero with code 2.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.cli.research import app as research_app
from iguanatrader.contexts.research.models import (
    ResearchFact,
    ResearchSource,
    SymbolUniverse,
)
from iguanatrader.contexts.research.ports import ResearchFactDraft
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
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'ig_ingest_test.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'ig_ingest_test.db').as_posix()}"


@pytest.fixture
async def schema_session_factory(
    engine_with_schema: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine_with_schema)


def _run_research(
    db_url: str,
    *args: str,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, str]:
    monkeypatch.setenv("IGUANA_DATABASE_URL", db_url)
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "iguanatrader-test test@example.com")
    runner = CliRunner()
    result = runner.invoke(research_app, list(args))
    output = result.output or ""
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        import traceback

        output += "\n\n--- exception ---\n" + "".join(
            traceback.format_exception(
                type(result.exception), result.exception, result.exception.__traceback__
            )
        )
    return result.exit_code, output


async def _seed_tenant_symbol_source(
    sf: async_sessionmaker[AsyncSession],
    *,
    symbol: str = "NVDA",
) -> tuple[UUID, UUID]:
    """Insert minimum rows for the CLI to succeed: Tenant + SymbolUniverse + ResearchSource."""
    tenant_id = uuid4()
    symbol_universe_id = uuid4()
    async with sf() as session:
        session.add(Tenant(id=tenant_id, name="cli-ingest-tenant", feature_flags={}))
        session.add(
            ResearchSource(
                id="sec_edgar",
                display_name="SEC EDGAR",
                tier=1,
                pit_class="A",
            )
        )
        await session.commit()
    # SymbolUniverse insert needs tenant context so the listener stamps it.
    from iguanatrader.shared.contextvars import with_tenant_context

    async with with_tenant_context(tenant_id), sf() as session:
        session.add(
            SymbolUniverse(
                id=symbol_universe_id,
                tenant_id=tenant_id,
                symbol=symbol,
                exchange="NASDAQ",
            )
        )
        await session.commit()
    return tenant_id, symbol_universe_id


def _fake_drafts(*, count: int = 3) -> list[ResearchFactDraft]:
    """Build N synthetic drafts that the patched adapter will yield."""
    now = datetime(2026, 1, 15, tzinfo=UTC)
    return [
        ResearchFactDraft(
            source_id="sec_edgar",
            fact_kind=f"sec_xbrl.us-gaap.TestConcept{i}",
            effective_from=now,
            recorded_from=now,
            source_url=f"https://data.sec.gov/test-{i}",
            retrieval_method="api",
            retrieved_at=now,
            value_numeric=Decimal(f"{(i + 1) * 100}"),
            unit="USD",
            fact_metadata={"test_index": i},
            dedupe_key=f"sec_edgar:test:{i}",
        )
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_ingest_sec_edgar_persists_drafts(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, symbol_universe_id = await _seed_tenant_symbol_source(schema_session_factory)

    drafts = _fake_drafts(count=3)

    def _fake_fetch(self: Any, symbol: str, since: datetime | None) -> list[ResearchFactDraft]:
        return drafts

    monkeypatch.setattr(
        "iguanatrader.contexts.research.sources.sec_edgar.SECEdgarSource.fetch",
        _fake_fetch,
    )

    code, output = _run_research(
        db_url,
        "ingest",
        "sec-edgar",
        "NVDA",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output
    assert "facts_inserted=3" in output

    async with schema_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(ResearchFact).where(
                        ResearchFact.symbol_universe_id == symbol_universe_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 3
    # All rows reference the resolved symbol + the seeded source.
    for row in rows:
        assert row.symbol_universe_id == symbol_universe_id
        assert row.source_id == "sec_edgar"


@pytest.mark.asyncio
async def test_ingest_sec_edgar_unknown_symbol_exits_non_zero(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_tenant_symbol_source(schema_session_factory, symbol="NVDA")

    code, output = _run_research(
        db_url,
        "ingest",
        "sec-edgar",
        "DOES-NOT-EXIST",
        monkeypatch=monkeypatch,
    )
    assert code != 0
    assert "not registered" in output


@pytest.mark.asyncio
async def test_ingest_sec_edgar_forwards_since_to_adapter(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_tenant_symbol_source(schema_session_factory)

    captured: dict[str, Any] = {}

    def _fake_fetch(self: Any, symbol: str, since: datetime | None) -> list[ResearchFactDraft]:
        captured["since"] = since
        return []

    monkeypatch.setattr(
        "iguanatrader.contexts.research.sources.sec_edgar.SECEdgarSource.fetch",
        _fake_fetch,
    )

    code, output = _run_research(
        db_url,
        "ingest",
        "sec-edgar",
        "NVDA",
        "--since",
        "2024-01-01",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output
    assert captured["since"] == datetime(2024, 1, 1, tzinfo=UTC)


def test_ingest_sec_edgar_invalid_since_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "iguanatrader-test test@example.com")
    runner = CliRunner()
    result = runner.invoke(
        research_app,
        ["ingest", "sec-edgar", "NVDA", "--since", "not-a-date"],
    )
    assert result.exit_code == 2
    assert "ISO 8601" in (result.output or "")
