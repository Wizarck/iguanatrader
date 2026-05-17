"""Integration test for ``iguanatrader research ingest openbb``.

Asserts CLI control flow without hitting the live sidecar HTTP. The
adapter's ``fetch`` is monkeypatched to return synthetic drafts so we
validate:

1. Happy path — drafts persist with ``symbol_universe_id`` stamped.
2. Unknown symbol — exits non-zero with a registration hint.
3. Adapter ``.close()`` is called even when ingestion raises.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
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
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'ig_openbb_test.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'ig_openbb_test.db').as_posix()}"


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
    # Adapter reads OPENBB_SIDECAR_URL on construction; any string is fine
    # because the fetch is monkeypatched away.
    monkeypatch.setenv("OPENBB_SIDECAR_URL", "http://test-fake-sidecar:8765")
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
    tenant_id = uuid4()
    symbol_universe_id = uuid4()
    async with sf() as session:
        session.add(Tenant(id=tenant_id, name="cli-openbb-tenant", feature_flags={}))
        session.add(
            ResearchSource(
                id="openbb-sidecar",
                display_name="OpenBB sidecar",
                tier=1,
                pit_class="B",
            )
        )
        await session.commit()
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


def _fake_drafts() -> list[ResearchFactDraft]:
    now = datetime(2026, 1, 15, tzinfo=UTC)
    payload_bytes = b'{"_test": "openbb"}'
    return [
        ResearchFactDraft(
            source_id="openbb-sidecar",
            fact_kind=fact_kind,
            effective_from=now,
            recorded_from=now,
            source_url=f"http://test-fake-sidecar:8765/v1/equity/{endpoint}/NVDA",
            retrieval_method="http",
            retrieved_at=now,
            value_jsonb={"endpoint": endpoint, "stub": True},
        ).with_payload(payload_bytes)
        for endpoint, fact_kind in [
            ("fundamentals", "fundamentals"),
            ("ratings", "analyst_ratings"),
            ("esg", "esg_score"),
        ]
    ]


@pytest.mark.asyncio
async def test_ingest_openbb_persists_drafts(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, symbol_universe_id = await _seed_tenant_symbol_source(schema_session_factory)

    drafts = _fake_drafts()
    closed_flag = {"value": False}

    def _fake_fetch(self: Any, symbol: str, since: Any) -> list[ResearchFactDraft]:
        return drafts

    def _fake_close(self: Any) -> None:
        closed_flag["value"] = True

    monkeypatch.setattr(
        "iguanatrader.contexts.research.sources.openbb_sidecar.OpenBBSidecarSource.fetch",
        _fake_fetch,
    )
    monkeypatch.setattr(
        "iguanatrader.contexts.research.sources.openbb_sidecar.OpenBBSidecarSource.close",
        _fake_close,
    )

    code, output = _run_research(
        db_url,
        "ingest",
        "openbb",
        "NVDA",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output
    assert "facts_inserted=3" in output
    assert closed_flag["value"] is True

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
    fact_kinds = {row.fact_kind for row in rows}
    assert fact_kinds == {"fundamentals", "analyst_ratings", "esg_score"}


@pytest.mark.asyncio
async def test_ingest_openbb_unknown_symbol_exits_non_zero(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_tenant_symbol_source(schema_session_factory, symbol="NVDA")

    code, output = _run_research(
        db_url,
        "ingest",
        "openbb",
        "DOES-NOT-EXIST",
        monkeypatch=monkeypatch,
    )
    assert code != 0
    assert "not registered" in output


@pytest.mark.asyncio
async def test_ingest_openbb_closes_adapter_on_error(
    db_url: str,
    engine_with_schema: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_tenant_symbol_source(schema_session_factory)

    closed_flag = {"value": False}

    def _fake_fetch(self: Any, symbol: str, since: Any) -> list[ResearchFactDraft]:
        raise RuntimeError("simulated upstream blowup")

    def _fake_close(self: Any) -> None:
        closed_flag["value"] = True

    monkeypatch.setattr(
        "iguanatrader.contexts.research.sources.openbb_sidecar.OpenBBSidecarSource.fetch",
        _fake_fetch,
    )
    monkeypatch.setattr(
        "iguanatrader.contexts.research.sources.openbb_sidecar.OpenBBSidecarSource.close",
        _fake_close,
    )

    code, _ = _run_research(
        db_url,
        "ingest",
        "openbb",
        "NVDA",
        monkeypatch=monkeypatch,
    )
    assert code != 0
    assert closed_flag["value"] is True, "adapter.close() must run even on raise"
