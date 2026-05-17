"""Tier-A YoY growth computation from XBRL historical facts (slice R3 growth).

Verifies :class:`TierAFeatureProvider` computes ``eps_growth_yoy`` and
``revenue_growth_yoy`` by walking the most recent FY-period XBRL facts
and dividing (latest − prior) / |prior|.

Restatement collapse: a 10-K/A re-filing of the same fiscal year wins
over the original 10-K (latest ``recorded_from`` per ``effective_from``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from iguanatrader.contexts.research.feature_provider.tier_a import (
    TierAFeatureProvider,
)
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 5, 17, 18, 0, 0, tzinfo=UTC)


def _xbrl_draft(
    *,
    universe_id: UUID,
    fact_kind: str,
    effective_from: datetime,
    recorded_from: datetime,
    value: Decimal,
    fiscal_period: str = "FY",
    fiscal_year: int = 2024,
    accession: str = "0000320193-24-000001",
) -> ResearchFactDraft:
    """Build an SEC-EDGAR-style XBRL draft fact."""
    return ResearchFactDraft(
        source_id="sec_edgar",
        symbol_universe_id=universe_id,
        fact_kind=fact_kind,
        effective_from=effective_from,
        recorded_from=recorded_from,
        source_url="https://data.sec.gov/submissions/CIK0000320193.json",
        retrieval_method="api",
        retrieved_at=recorded_from,
        value_numeric=value,
        unit="USD/shares",
        fact_metadata={
            "cik": 320193,
            "form": "10-K",
            "accession_number": accession,
            "taxonomy": "us-gaap",
            "concept": fact_kind.split(".")[-1],
            "fiscal_period": fiscal_period,
            "fiscal_year": fiscal_year,
        },
        dedupe_key=f"sec_edgar:xbrl:320193:{fact_kind}:fy={fiscal_year}:fp={fiscal_period}:accn={accession}",
    ).with_payload(b'{"raw": "xbrl"}')


@pytest.mark.asyncio
async def test_eps_growth_yoy_from_two_consecutive_fy_filings(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """Two FY EPS rows → ``eps_growth_yoy`` = (FY24 − FY23) / |FY23|."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    fy23_end = datetime(2023, 9, 30, tzinfo=UTC)
    fy24_end = datetime(2024, 9, 30, tzinfo=UTC)

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _xbrl_draft(
                universe_id=universe_id,
                fact_kind="sec_xbrl.us-gaap.EarningsPerShareDiluted",
                effective_from=fy23_end,
                recorded_from=fy23_end + timedelta(days=60),
                value=Decimal("6.13"),
                fiscal_year=2023,
                accession="0000320193-23-000001",
            )
        )
        await repository.insert_fact(
            _xbrl_draft(
                universe_id=universe_id,
                fact_kind="sec_xbrl.us-gaap.EarningsPerShareDiluted",
                effective_from=fy24_end,
                recorded_from=fy24_end + timedelta(days=60),
                value=Decimal("7.36"),
                fiscal_year=2024,
                accession="0000320193-24-000001",
            )
        )
        await with_session.commit()

        provider = TierAFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=None)

    yoy, tier = bundle.values["eps_growth_yoy"]
    assert tier == "A"
    expected = (Decimal("7.36") - Decimal("6.13")) / abs(Decimal("6.13"))
    assert yoy is not None
    assert abs(yoy - expected) < Decimal("0.0001")


@pytest.mark.asyncio
async def test_yoy_uses_latest_restatement_when_10ka_supersedes(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """A 10-K/A re-filing the same fiscal year overrides the original."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    fy23_end = datetime(2023, 9, 30, tzinfo=UTC)
    fy24_end = datetime(2024, 9, 30, tzinfo=UTC)

    async with with_tenant_context(tenant_id):
        # FY23 original
        await repository.insert_fact(
            _xbrl_draft(
                universe_id=universe_id,
                fact_kind="sec_xbrl.us-gaap.Revenues",
                effective_from=fy23_end,
                recorded_from=fy23_end + timedelta(days=60),
                value=Decimal("383285000000"),
                fiscal_year=2023,
                accession="0000320193-23-000001",
            )
        )
        # FY23 restated (10-K/A) — recorded later, same effective_from.
        await repository.insert_fact(
            _xbrl_draft(
                universe_id=universe_id,
                fact_kind="sec_xbrl.us-gaap.Revenues",
                effective_from=fy23_end,
                recorded_from=fy23_end + timedelta(days=180),
                value=Decimal("400000000000"),
                fiscal_year=2023,
                accession="0000320193-23-AMEND",
            )
        )
        await repository.insert_fact(
            _xbrl_draft(
                universe_id=universe_id,
                fact_kind="sec_xbrl.us-gaap.Revenues",
                effective_from=fy24_end,
                recorded_from=fy24_end + timedelta(days=60),
                value=Decimal("420000000000"),
                fiscal_year=2024,
                accession="0000320193-24-000001",
            )
        )
        await with_session.commit()

        provider = TierAFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=None)

    yoy, _tier = bundle.values["revenue_growth_yoy"]
    # Restated prior (400B), not original (383B).
    expected = (Decimal("420000000000") - Decimal("400000000000")) / Decimal("400000000000")
    assert yoy is not None
    assert abs(yoy - expected) < Decimal("0.0001")


@pytest.mark.asyncio
async def test_quarterly_only_filings_yield_no_yoy(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """If the company has only 10-Q facts (``fp=Qx``), YoY is None."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    q3_end = datetime(2024, 6, 30, tzinfo=UTC)
    q2_end = datetime(2024, 3, 31, tzinfo=UTC)

    async with with_tenant_context(tenant_id):
        for end, fp, val in (
            (q3_end, "Q3", Decimal("1.50")),
            (q2_end, "Q2", Decimal("1.40")),
        ):
            await repository.insert_fact(
                _xbrl_draft(
                    universe_id=universe_id,
                    fact_kind="sec_xbrl.us-gaap.EarningsPerShareDiluted",
                    effective_from=end,
                    recorded_from=end + timedelta(days=45),
                    value=val,
                    fiscal_period=fp,
                    fiscal_year=2024,
                    accession=f"acc-{fp}",
                )
            )
        await with_session.commit()

        provider = TierAFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=None)

    assert bundle.values["eps_growth_yoy"] == (None, "A")


@pytest.mark.asyncio
async def test_single_fy_filing_yields_no_yoy(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """A single FY row can't anchor YoY — return None."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    fy_end = datetime(2024, 9, 30, tzinfo=UTC)

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _xbrl_draft(
                universe_id=universe_id,
                fact_kind="sec_xbrl.us-gaap.EarningsPerShareDiluted",
                effective_from=fy_end,
                recorded_from=fy_end + timedelta(days=60),
                value=Decimal("7.36"),
            )
        )
        await with_session.commit()

        provider = TierAFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=None)

    assert bundle.values["eps_growth_yoy"] == (None, "A")


@pytest.mark.asyncio
async def test_zero_prior_returns_none_not_divide_by_zero(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """Prior-period value 0 → None (can't normalise an undefined base)."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    fy23_end = datetime(2023, 9, 30, tzinfo=UTC)
    fy24_end = datetime(2024, 9, 30, tzinfo=UTC)

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(
            _xbrl_draft(
                universe_id=universe_id,
                fact_kind="sec_xbrl.us-gaap.EarningsPerShareDiluted",
                effective_from=fy23_end,
                recorded_from=fy23_end + timedelta(days=60),
                value=Decimal("0"),
                fiscal_year=2023,
                accession="acc-2023",
            )
        )
        await repository.insert_fact(
            _xbrl_draft(
                universe_id=universe_id,
                fact_kind="sec_xbrl.us-gaap.EarningsPerShareDiluted",
                effective_from=fy24_end,
                recorded_from=fy24_end + timedelta(days=60),
                value=Decimal("7.36"),
                fiscal_year=2024,
                accession="acc-2024",
            )
        )
        await with_session.commit()

        provider = TierAFeatureProvider(repository)
        bundle = await provider.fetch(symbol="AAPL", since=None)

    assert bundle.values["eps_growth_yoy"] == (None, "A")
