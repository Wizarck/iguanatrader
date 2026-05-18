"""Unit tests for ``OnDemandIngestionService`` (slice research-ad-hoc-mode).

Drives the service with a fake OpenBB sidecar source so the test runs
without a real sidecar container. Verifies:

1. ``ingest`` calls both adapter generators (``fetch`` + ``fetch_prices``)
   and persists each yielded draft.
2. Each persisted fact carries the caller-supplied
   ``symbol_universe_id`` (the adapter emits None — the service must
   stamp it).
3. A per-draft insert failure is logged and skipped — does NOT abort
   the remaining endpoints.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from iguanatrader.contexts.research.models import (
    ResearchFact,
    ResearchSource,
    SymbolUniverse,
)
from iguanatrader.contexts.research.on_demand_ingestion import (
    OnDemandIngestionService,
)
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.contexts.research.sources.base import ResearchFactDraft
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    db_path = tmp_path / "ig_on_demand_ingest.db"
    eng = engine_factory(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


def _draft(fact_kind: str, *, source_id: str = "openbb-sidecar") -> ResearchFactDraft:
    now = datetime(2026, 5, 18, tzinfo=UTC)
    payload = {"value": 42.0, "as_of_date": now.isoformat()}
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    return ResearchFactDraft(
        source_id=source_id,
        fact_kind=fact_kind,
        effective_from=now,
        recorded_from=now,
        source_url=f"http://openbb_sidecar:8765/v1/equity/{fact_kind}/NVDA",
        retrieval_method="api",
        retrieved_at=now,
        value_jsonb=payload,
    ).with_payload(payload_bytes)


class _FakeOpenBBSource:
    """Stand-in for OpenBBSidecarSource — yields scripted drafts."""

    def __init__(
        self,
        *,
        fetch_drafts: list[ResearchFactDraft],
        prices_drafts: list[ResearchFactDraft],
    ) -> None:
        self._fetch_drafts = fetch_drafts
        self._prices_drafts = prices_drafts
        self.fetch_calls: list[str] = []
        self.prices_calls: list[tuple[str, str | None, str | None]] = []

    def fetch(self, symbol: str, since: datetime | None) -> Iterable[ResearchFactDraft]:
        self.fetch_calls.append(symbol)
        yield from self._fetch_drafts

    def fetch_prices(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterable[ResearchFactDraft]:
        self.prices_calls.append((symbol, start_date, end_date))
        yield from self._prices_drafts


async def _seed_tenant_and_universe(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol_universe_id: UUID,
) -> None:
    # Tenant + ResearchSource are __tenant_scoped__ = False (cross-tenant
    # catalogue), so they can be inserted without a tenant context.
    async with sf() as s:
        s.add(Tenant(id=tenant_id, name=f"t-{tenant_id.hex[:6]}", feature_flags={}))
        s.add(
            ResearchSource(
                id="openbb-sidecar",
                display_name="OpenBB sidecar",
                tier=2,
                pit_class="B",
            )
        )
        await s.commit()
    # SymbolUniverse is tenant-scoped — needs the listener to stamp tenant_id.
    async with with_tenant_context(tenant_id), sf() as s:
        session_var.set(s)
        s.add(
            SymbolUniverse(
                id=symbol_universe_id,
                tenant_id=tenant_id,
                symbol="NVDA",
                exchange="NASDAQ",
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_ingest_persists_drafts_from_both_endpoints(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    sym_uid = uuid4()
    await _seed_tenant_and_universe(sf, tenant_id=tid, symbol_universe_id=sym_uid)

    fake = _FakeOpenBBSource(
        fetch_drafts=[_draft("fundamentals"), _draft("analyst_ratings"), _draft("esg_score")],
        prices_drafts=[_draft("historical_prices_window")],
    )

    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        repo = ResearchRepository()
        service = OnDemandIngestionService(repository=repo, openbb_source=fake)
        outcome = await service.ingest(symbol="NVDA", symbol_universe_id=sym_uid)
        await session.commit()

        rows = (await session.execute(sa.select(ResearchFact))).scalars().all()

    assert outcome.facts_inserted == 4
    assert outcome.endpoints_attempted == 4
    assert {r.fact_kind for r in rows} == {
        "fundamentals",
        "analyst_ratings",
        "esg_score",
        "historical_prices_window",
    }
    # Each row carries the caller-supplied symbol_universe_id.
    for row in rows:
        assert row.symbol_universe_id == sym_uid
    assert fake.fetch_calls == ["NVDA"]
    assert len(fake.prices_calls) == 1
    assert fake.prices_calls[0][0] == "NVDA"


@pytest.mark.asyncio
async def test_ingest_with_empty_prices_window_skips_gracefully(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    """Empty ``fetch_prices`` (sidecar 4xx for the symbol) is non-fatal.

    The ``OpenBBSidecarSource._get_or_skip`` adapter returns ``None`` on
    4xx and ``fetch_prices`` yields nothing in that case. The ingest
    should still succeed with whatever the other endpoints returned.
    """
    tid = uuid4()
    sym_uid = uuid4()
    await _seed_tenant_and_universe(sf, tenant_id=tid, symbol_universe_id=sym_uid)

    fake = _FakeOpenBBSource(
        fetch_drafts=[_draft("fundamentals")],
        prices_drafts=[],
    )

    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        repo = ResearchRepository()
        service = OnDemandIngestionService(repository=repo, openbb_source=fake)
        outcome = await service.ingest(symbol="NVDA", symbol_universe_id=sym_uid)
        await session.commit()

    assert outcome.facts_inserted == 1
    assert outcome.endpoints_attempted == 1
