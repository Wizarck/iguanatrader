"""Integration test for ``iguanatrader research ingest fred``.

Asserts CLI argument parsing + control flow without hitting the live
FRED API. The adapter's ``fetch_series`` is monkeypatched to return
fixed drafts so we validate:

1. Happy path — drafts from each requested series persist to
   ``research_facts`` with ``symbol_universe_id=NULL`` (macro is global).
2. ``--backfill 5y`` translates to a ``since`` ~5*365 days in the past.
3. ``--since YYYY-MM-DD`` overrides ``--backfill`` when both present.
4. Empty / invalid ``--series`` exits non-zero.
5. Invalid ``--backfill`` format exits 2.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.cli.research import app as research_app
from iguanatrader.contexts.research.models import ResearchFact, ResearchSource
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
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'ig_fred_test.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'ig_fred_test.db').as_posix()}"


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
    monkeypatch.setenv("FRED_API_KEY", "test-fake-key")
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


async def _seed_tenant_source(
    sf: async_sessionmaker[AsyncSession],
) -> UUID:
    tenant_id = uuid4()
    async with sf() as session:
        session.add(Tenant(id=tenant_id, name="cli-fred-tenant", feature_flags={}))
        session.add(
            ResearchSource(
                id="fred",
                display_name="FRED",
                tier=1,
                pit_class="A",
            )
        )
        await session.commit()
    return tenant_id


def _fake_drafts_for_series(series_id: str, *, count: int = 3) -> list[ResearchFactDraft]:
    now = datetime(2026, 1, 15, tzinfo=UTC)
    payload_bytes = b'{"_test": "fred"}'
    return [
        ResearchFactDraft(
            source_id="fred",
            fact_kind=f"fred.{series_id}",
            effective_from=now,
            recorded_from=now,
            source_url=f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}",
            retrieval_method="api",
            retrieved_at=now,
            value_numeric=Decimal(f"{(i + 1) * 1.5}"),
            fact_metadata={"series_id": series_id, "idx": i},
            dedupe_key=f"fred:{series_id}:test-{i}",
        ).with_payload(payload_bytes)
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_ingest_fred_persists_per_series(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_tenant_source(schema_session_factory)

    captured: list[tuple[str, datetime | None]] = []

    def _fake_fetch(
        self: Any, series_id: str, since: datetime | None = None
    ) -> list[ResearchFactDraft]:
        captured.append((series_id, since))
        return _fake_drafts_for_series(series_id, count=2)

    monkeypatch.setattr(
        "iguanatrader.contexts.research.sources.fred.FREDSource.fetch_series",
        _fake_fetch,
    )

    code, output = _run_research(
        db_url,
        "ingest",
        "fred",
        "--series",
        "CPIAUCSL,UNRATE",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output
    assert "facts_inserted=4" in output
    assert [s for s, _ in captured] == ["CPIAUCSL", "UNRATE"]

    async with schema_session_factory() as session:
        rows = (await session.execute(select(ResearchFact))).scalars().all()
    assert len(rows) == 4
    for row in rows:
        assert row.source_id == "fred"
        assert row.symbol_universe_id is None  # Macro facts have no symbol scope.


@pytest.mark.asyncio
async def test_ingest_fred_backfill_translates_to_since(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_tenant_source(schema_session_factory)

    captured: dict[str, Any] = {}

    def _fake_fetch(
        self: Any, series_id: str, since: datetime | None = None
    ) -> list[ResearchFactDraft]:
        captured["since"] = since
        return []

    monkeypatch.setattr(
        "iguanatrader.contexts.research.sources.fred.FREDSource.fetch_series",
        _fake_fetch,
    )

    code, output = _run_research(
        db_url,
        "ingest",
        "fred",
        "--series",
        "GDP",
        "--backfill",
        "5y",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output
    since_dt = captured["since"]
    assert isinstance(since_dt, datetime)
    # 5y ≈ 1825 days back from now; allow ±2 days for clock skew across test runs.
    expected = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=1825
    )
    delta = abs((since_dt - expected).total_seconds())
    assert delta < 2 * 86400


@pytest.mark.asyncio
async def test_ingest_fred_since_overrides_backfill(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_tenant_source(schema_session_factory)

    captured: dict[str, Any] = {}

    def _fake_fetch(
        self: Any, series_id: str, since: datetime | None = None
    ) -> list[ResearchFactDraft]:
        captured["since"] = since
        return []

    monkeypatch.setattr(
        "iguanatrader.contexts.research.sources.fred.FREDSource.fetch_series",
        _fake_fetch,
    )

    code, output = _run_research(
        db_url,
        "ingest",
        "fred",
        "--series",
        "GDP",
        "--since",
        "2024-06-01",
        "--backfill",
        "5y",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output
    assert captured["since"] == datetime(2024, 6, 1, tzinfo=UTC)


def test_ingest_fred_empty_series_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "test-fake-key")
    runner = CliRunner()
    result = runner.invoke(
        research_app,
        ["ingest", "fred", "--series", " , , "],
    )
    assert result.exit_code == 2
    assert "at least one" in (result.output or "")


def test_ingest_fred_invalid_backfill_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "test-fake-key")
    runner = CliRunner()
    result = runner.invoke(
        research_app,
        ["ingest", "fred", "--series", "CPIAUCSL", "--backfill", "not-a-window"],
    )
    assert result.exit_code == 2
    assert "<N>d/m/y" in (result.output or "")
