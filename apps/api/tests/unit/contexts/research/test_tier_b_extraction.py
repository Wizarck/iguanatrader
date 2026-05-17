"""Tier-B feature extraction from OpenBB sidecar payloads (slice R3 value pillar).

Verifies the rewritten :class:`TierBFeatureProvider` pulls scalar features
out of ``value_jsonb`` payloads written by the OpenBB sidecar adapter
(``fact_kind`` values: ``fundamentals``, ``analyst_ratings``, ``esg_score``).
Pre-R3 the provider matched ``"openbb-sidecar.fundamentals"`` and read
``value_numeric`` — neither aligned with how the adapter actually writes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from iguanatrader.contexts.research.feature_provider.tier_b import (
    TierBFeatureProvider,
)
from iguanatrader.contexts.research.models import ResearchSource
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Times anchoring the test fixtures.
NOW = datetime(2026, 5, 17, 18, 0, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)
LATER = NOW + timedelta(hours=1)


async def _seed_openbb_source(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> None:
    """Add the cross-tenant ``openbb-sidecar`` source row.

    The conftest's ``seeded_world`` only inserts ``sec_edgar``. Tier-B
    tests need the openbb-sidecar source row so the foreign-key from
    ``research_facts.source_id`` resolves.
    """
    async with session_factory_fx() as s:
        s.add(
            ResearchSource(
                id="openbb-sidecar",
                display_name="OpenBB Sidecar (AGPL-isolated)",
                tier=2,
                pit_class="B",
                enabled=True,
            )
        )
        await s.commit()


def _draft_fundamentals(
    *,
    universe_id: UUID,
    recorded_from: datetime,
    payload: dict[str, Any],
) -> ResearchFactDraft:
    return ResearchFactDraft(
        source_id="openbb-sidecar",
        symbol_universe_id=universe_id,
        fact_kind="fundamentals",
        effective_from=recorded_from,
        recorded_from=recorded_from,
        source_url="http://openbb_sidecar:8765/v1/equity/fundamentals/AAPL",
        retrieval_method="api",
        retrieved_at=recorded_from,
        value_jsonb=payload,
    ).with_payload(b'{"raw": "fundamentals"}')


def _draft_ratings(
    *,
    universe_id: UUID,
    recorded_from: datetime,
    payload: dict[str, Any],
) -> ResearchFactDraft:
    return ResearchFactDraft(
        source_id="openbb-sidecar",
        symbol_universe_id=universe_id,
        fact_kind="analyst_ratings",
        effective_from=recorded_from,
        recorded_from=recorded_from,
        source_url="http://openbb_sidecar:8765/v1/equity/ratings/AAPL",
        retrieval_method="api",
        retrieved_at=recorded_from,
        value_jsonb=payload,
    ).with_payload(b'{"raw": "ratings"}')


@pytest.mark.asyncio
async def test_extracts_value_pillar_scalars_from_fundamentals_payload(
    seeded_world: dict[str, Any],
    session_factory_fx: async_sessionmaker[AsyncSession],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """``forward_pe`` + ``pb_ratio`` come out of ``value_jsonb`` keys."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]
    await _seed_openbb_source(session_factory_fx)

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _draft_fundamentals(
                universe_id=universe_id,
                recorded_from=EARLIER,
                payload={
                    "pe_ratio": 30.5,
                    "forward_pe": 24.0,
                    "price_to_book": 3.2,
                    "market_cap": 2_800_000_000_000,
                    "dividend_yield": 0.005,
                },
            )
        )
        await with_session.commit()

        provider = TierBFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=NOW)

    forward_pe, tier_fp = bundle.values["forward_pe"]
    pb_ratio, tier_pb = bundle.values["pb_ratio"]
    assert forward_pe == Decimal("24.0")
    assert pb_ratio == Decimal("3.2")
    assert tier_fp == "B"
    assert tier_pb == "B"

    # Citation map points the value features to the fundamentals fact id.
    assert "forward_pe" in bundle.fact_citations
    assert bundle.fact_citations["forward_pe"] == bundle.fact_citations["pb_ratio"]


@pytest.mark.asyncio
async def test_missing_payload_key_returns_none_not_raise(
    seeded_world: dict[str, Any],
    session_factory_fx: async_sessionmaker[AsyncSession],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """A fundamentals row without ``price_to_book`` yields ``pb_ratio=None``."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]
    await _seed_openbb_source(session_factory_fx)

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _draft_fundamentals(
                universe_id=universe_id,
                recorded_from=EARLIER,
                payload={"pe_ratio": 30.5, "forward_pe": 24.0},
            )
        )
        await with_session.commit()

        provider = TierBFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=NOW)

    assert bundle.values["pb_ratio"] == (None, "B")
    assert bundle.values["forward_pe"] == (Decimal("24.0"), "B")


@pytest.mark.asyncio
async def test_since_none_yields_all_none_backtest_safety(
    seeded_world: dict[str, Any],
    session_factory_fx: async_sessionmaker[AsyncSession],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """``since=None`` returns all features None (backtest-safe contract)."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]
    await _seed_openbb_source(session_factory_fx)

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _draft_fundamentals(
                universe_id=universe_id,
                recorded_from=EARLIER,
                payload={"forward_pe": 24.0, "price_to_book": 3.2},
            )
        )
        await with_session.commit()

        provider = TierBFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=None)

    for _name, (value, tier) in bundle.values.items():
        assert value is None
        assert tier == "B"


@pytest.mark.asyncio
async def test_recorded_after_since_excluded(
    seeded_world: dict[str, Any],
    session_factory_fx: async_sessionmaker[AsyncSession],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """A fact recorded AFTER ``since`` must NOT leak into a backtest."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]
    await _seed_openbb_source(session_factory_fx)

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _draft_fundamentals(
                universe_id=universe_id,
                recorded_from=LATER,
                payload={"forward_pe": 24.0, "price_to_book": 3.2},
            )
        )
        await with_session.commit()

        provider = TierBFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=NOW)

    assert bundle.values["forward_pe"] == (None, "B")
    assert bundle.values["pb_ratio"] == (None, "B")


@pytest.mark.asyncio
async def test_analyst_ratings_target_price_extracted(
    seeded_world: dict[str, Any],
    session_factory_fx: async_sessionmaker[AsyncSession],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """``analyst_target_price`` + ``analyst_count`` pull from the ratings fact."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]
    await _seed_openbb_source(session_factory_fx)

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _draft_ratings(
                universe_id=universe_id,
                recorded_from=EARLIER,
                payload={
                    "consensus": "strong_buy",
                    "target_price": 380.0,
                    "analyst_count": 57,
                },
            )
        )
        await with_session.commit()

        provider = TierBFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=NOW)

    assert bundle.values["analyst_target_price"] == (Decimal("380.0"), "B")
    assert bundle.values["analyst_count"] == (Decimal("57"), "B")
