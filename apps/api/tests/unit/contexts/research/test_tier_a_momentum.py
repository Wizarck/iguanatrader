"""Tier-A momentum computation from historical_prices_window facts (slice R3 momentum).

Verifies :class:`TierAFeatureProvider` computes ``return_3m``,
``return_12m``, and ``relative_strength`` by walking the bar series
inside one ``historical_prices_window`` fact's ``value_jsonb``. The
benchmark (SPY) is fetched via the same fact_kind under its own symbol
universe row.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.research.feature_provider.tier_a import (
    BENCHMARK_SYMBOL,
    TierAFeatureProvider,
)
from iguanatrader.contexts.research.models import (
    ResearchSource,
    SymbolUniverse,
)
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 5, 17, 18, 0, 0, tzinfo=UTC)
TODAY = NOW.date()


async def _seed_openbb_source_and_spy(
    session_factory_fx: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
) -> UUID:
    """Insert openbb-sidecar source + SPY symbol; return SPY's universe id."""
    spy_id = uuid4()
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
    async with with_tenant_context(tenant_id), session_factory_fx() as s:
        s.add(
            SymbolUniverse(
                id=spy_id,
                tenant_id=tenant_id,
                symbol=BENCHMARK_SYMBOL,
                exchange="NYSE",
            )
        )
        await s.commit()
    return spy_id


def _bar(d: date, close: float) -> dict[str, Any]:
    return {
        "date": d.isoformat(),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "adj_close": close,
        "volume": 100,
    }


def _price_draft(
    *,
    universe_id: UUID,
    recorded_from: datetime,
    bars: list[dict[str, Any]],
) -> ResearchFactDraft:
    return ResearchFactDraft(
        source_id="openbb-sidecar",
        symbol_universe_id=universe_id,
        fact_kind="historical_prices_window",
        effective_from=recorded_from,
        recorded_from=recorded_from,
        source_url="http://openbb_sidecar:8765/v1/equity/historical_prices/AAPL",
        retrieval_method="api",
        retrieved_at=recorded_from,
        value_jsonb={
            "symbol": "AAPL",
            "start_date": bars[0]["date"] if bars else None,
            "end_date": bars[-1]["date"] if bars else None,
            "bars": bars,
        },
    ).with_payload(b'{"raw": "prices"}')


@pytest.mark.asyncio
async def test_returns_computed_from_bar_series(
    seeded_world: dict[str, Any],
    session_factory_fx: async_sessionmaker[AsyncSession],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """3-month and 12-month returns come out of the closes in ``value_jsonb``."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]
    await _seed_openbb_source_and_spy(session_factory_fx, tenant_id)

    bars = [
        _bar(TODAY - timedelta(days=365), 100.0),
        _bar(TODAY - timedelta(days=90), 110.0),
        _bar(TODAY - timedelta(days=1), 132.0),
    ]

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _price_draft(
                universe_id=universe_id,
                recorded_from=NOW - timedelta(hours=2),
                bars=bars,
            )
        )
        await with_session.commit()

        provider = TierAFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=NOW)

    ret_3m, _t1 = bundle.values["return_3m"]
    ret_12m, _t2 = bundle.values["return_12m"]
    # 132 from 110 over 3m ≈ +20%
    assert ret_3m is not None
    assert abs(ret_3m - Decimal("0.2")) < Decimal("0.001")
    # 132 from 100 over 12m = +32%
    assert ret_12m is not None
    assert abs(ret_12m - Decimal("0.32")) < Decimal("0.001")


@pytest.mark.asyncio
async def test_relative_strength_normalises_vs_spy_benchmark(
    seeded_world: dict[str, Any],
    session_factory_fx: async_sessionmaker[AsyncSession],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """``relative_strength`` = clip(0.5 + (sym_ret - spy_ret)/2, 0, 1)."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]
    spy_id = await _seed_openbb_source_and_spy(session_factory_fx, tenant_id)

    # Symbol returned +30% over 12m, SPY returned +10%.
    sym_bars = [
        _bar(TODAY - timedelta(days=365), 100.0),
        _bar(TODAY - timedelta(days=1), 130.0),
    ]
    spy_bars = [
        _bar(TODAY - timedelta(days=365), 400.0),
        _bar(TODAY - timedelta(days=1), 440.0),
    ]

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _price_draft(
                universe_id=universe_id,
                recorded_from=NOW - timedelta(hours=2),
                bars=sym_bars,
            )
        )
        await repository.insert_fact(
            _price_draft(
                universe_id=spy_id,
                recorded_from=NOW - timedelta(hours=2),
                bars=spy_bars,
            )
        )
        await with_session.commit()

        provider = TierAFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=NOW)

    rel, _tier = bundle.values["relative_strength"]
    # 0.5 + (0.30 - 0.10) / 2 = 0.6
    assert rel is not None
    assert abs(rel - Decimal("0.6")) < Decimal("0.001")


@pytest.mark.asyncio
async def test_relative_strength_clipped_to_zero_one(
    seeded_world: dict[str, Any],
    session_factory_fx: async_sessionmaker[AsyncSession],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """Extreme outperformance saturates at 1.0; extreme underperformance at 0.0."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]
    spy_id = await _seed_openbb_source_and_spy(session_factory_fx, tenant_id)

    # Symbol triples; SPY drops 50% — delta = 3.5 → 0.5 + 1.75 = 2.25 → clip to 1.
    sym_bars = [
        _bar(TODAY - timedelta(days=365), 50.0),
        _bar(TODAY - timedelta(days=1), 150.0),
    ]
    spy_bars = [
        _bar(TODAY - timedelta(days=365), 400.0),
        _bar(TODAY - timedelta(days=1), 200.0),
    ]

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _price_draft(
                universe_id=universe_id,
                recorded_from=NOW - timedelta(hours=2),
                bars=sym_bars,
            )
        )
        await repository.insert_fact(
            _price_draft(
                universe_id=spy_id,
                recorded_from=NOW - timedelta(hours=2),
                bars=spy_bars,
            )
        )
        await with_session.commit()

        provider = TierAFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=NOW)

    rel, _tier = bundle.values["relative_strength"]
    assert rel == Decimal("1")


@pytest.mark.asyncio
async def test_missing_benchmark_yields_none_relative_strength_but_keeps_returns(
    seeded_world: dict[str, Any],
    session_factory_fx: async_sessionmaker[AsyncSession],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """When SPY isn't ingested, absolute returns still populate; rel-strength is None."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]
    await _seed_openbb_source_and_spy(session_factory_fx, tenant_id)

    bars = [
        _bar(TODAY - timedelta(days=365), 100.0),
        _bar(TODAY - timedelta(days=1), 110.0),
    ]

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _price_draft(
                universe_id=universe_id,
                recorded_from=NOW - timedelta(hours=2),
                bars=bars,
            )
        )
        # NOTE: no SPY price fact inserted.
        await with_session.commit()

        provider = TierAFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=NOW)

    ret_12m, _t1 = bundle.values["return_12m"]
    rel, _t2 = bundle.values["relative_strength"]
    assert ret_12m is not None
    assert rel is None


@pytest.mark.asyncio
async def test_no_price_fact_yields_all_none_momentum(
    seeded_world: dict[str, Any],
    session_factory_fx: async_sessionmaker[AsyncSession],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """If the symbol has no price-window fact, momentum features are None."""
    tenant_id = seeded_world["tenant_id"]
    await _seed_openbb_source_and_spy(session_factory_fx, tenant_id)

    async with with_tenant_context(tenant_id):
        provider = TierAFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=NOW)

    assert bundle.values["return_3m"] == (None, "A")
    assert bundle.values["return_12m"] == (None, "A")
    assert bundle.values["relative_strength"] == (None, "A")
