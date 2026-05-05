"""Bitemporal point-in-time query correctness for :class:`ResearchRepository`.

Covers spec scenarios under "research_facts persists with dual-axis
bitemporal timestamps":

* ``as_of`` returns a row when both temporal predicates are satisfied.
* ``as_of`` excludes a row whose ``recorded_from > at`` (knowledge
  hadn't arrived yet).
* ``as_of`` excludes a row whose ``effective_to <= at`` (no longer
  effective in world).
* Supersession flow: insert R1, supersede(R1, T2), insert R2; assert
  ``as_of(at=T1.5) == [R1]`` and ``as_of(at=T2.5) == [R2]``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy.ext.asyncio import AsyncSession

UTC = timezone.utc

# Times anchoring the dual-axis fixtures. T1 < T1_5 < T2 < T2_5.
T1 = datetime(2024, 4, 25, 10, 0, 0, tzinfo=UTC)
T1_5 = datetime(2024, 4, 25, 12, 0, 0, tzinfo=UTC)
T2 = datetime(2024, 4, 26, 10, 0, 0, tzinfo=UTC)
T2_5 = datetime(2024, 4, 26, 12, 0, 0, tzinfo=UTC)


def _draft(
    *,
    source_id: str,
    universe_id: UUID,
    effective_from: datetime,
    recorded_from: datetime,
    value: Decimal = Decimal("1.0"),
) -> ResearchFactDraft:
    """Build a minimal valid :class:`ResearchFactDraft` with inline payload."""
    return ResearchFactDraft(
        source_id=source_id,
        symbol_universe_id=universe_id,
        fact_kind="fundamental.eps",
        effective_from=effective_from,
        recorded_from=recorded_from,
        source_url="https://example.test/edgar/AAPL/q1-2024.json",
        retrieval_method="api",
        retrieved_at=recorded_from,
        value_numeric=value,
        unit="USD",
        currency="USD",
    ).with_payload(b'{"raw": "edgar-q1-2024"}')


@pytest.mark.asyncio
async def test_as_of_returns_row_when_both_axes_satisfied(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """``as_of(at)`` returns a fact whose effective_from + recorded_from ≤ at."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        draft = _draft(
            source_id="sec_edgar",
            universe_id=universe_id,
            effective_from=T1,
            recorded_from=T2,
        )
        await repository.insert_fact(draft)
        await with_session.commit()

        # at >= recorded_from -> visible.
        results = await repository.as_of("AAPL", T2_5)
    assert len(results) == 1
    assert results[0].fact_kind == "fundamental.eps"


@pytest.mark.asyncio
async def test_as_of_excludes_row_with_recorded_from_after_at(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """A fact whose knowledge time is in the future of ``at`` is invisible."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        # Recorded at T2 — querying for T1_5 (before recorded_from) MUST
        # return nothing: at the time of the query we hadn't learned the
        # fact yet.
        await repository.insert_fact(
            _draft(
                source_id="sec_edgar",
                universe_id=universe_id,
                effective_from=T1,
                recorded_from=T2,
            )
        )
        await with_session.commit()

        results = await repository.as_of("AAPL", T1_5)
    assert results == []


@pytest.mark.asyncio
async def test_as_of_excludes_row_whose_effective_to_le_at(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """A fact whose ``effective_to <= at`` is no longer effective."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        draft = ResearchFactDraft(
            source_id="sec_edgar",
            symbol_universe_id=universe_id,
            fact_kind="fundamental.eps",
            effective_from=T1,
            effective_to=T2,
            recorded_from=T1,
            source_url="https://example.test/edgar/AAPL/q1-2024.json",
            retrieval_method="api",
            retrieved_at=T1,
            value_numeric=Decimal("1.0"),
        ).with_payload(b'{"raw": "edgar-q1-2024"}')
        await repository.insert_fact(draft)
        await with_session.commit()

        # effective_to=T2; at=T2_5 -> excluded (T2 < T2_5).
        results_after = await repository.as_of("AAPL", T2_5)
        # at=T1_5 -> still effective.
        results_during = await repository.as_of("AAPL", T1_5)
    assert results_after == []
    assert len(results_during) == 1


@pytest.mark.asyncio
async def test_supersession_flow_returns_correct_row_per_knowledge_time(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """Insert R1, supersede(R1, T2), insert R2; PiT queries return the right row."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        # R1 — recorded at T1 with value 1.0.
        r1 = await repository.insert_fact(
            _draft(
                source_id="sec_edgar",
                universe_id=universe_id,
                effective_from=T1,
                recorded_from=T1,
                value=Decimal("1.0"),
            )
        )
        await with_session.commit()

        # Supersede R1 at T2 (sets recorded_to = T2 via raw SQL — passes the
        # narrow L2 trigger exception).
        await repository.supersede_fact(r1.id, T2)
        await with_session.commit()

        # R2 — corrected value, recorded at T2 with value 2.0.
        await repository.insert_fact(
            _draft(
                source_id="sec_edgar",
                universe_id=universe_id,
                effective_from=T1,
                recorded_from=T2,
                value=Decimal("2.0"),
            )
        )
        await with_session.commit()

        results_at_t1_5 = await repository.as_of("AAPL", T1_5)
        results_at_t2_5 = await repository.as_of("AAPL", T2_5)
        results_just_before_t2 = await repository.as_of(
            "AAPL", T2 - timedelta(microseconds=1)
        )

    assert len(results_at_t1_5) == 1
    assert results_at_t1_5[0].value_numeric == Decimal("1.000000000000")

    assert len(results_at_t2_5) == 1
    assert results_at_t2_5[0].value_numeric == Decimal("2.000000000000")

    assert len(results_just_before_t2) == 1
    assert results_just_before_t2[0].value_numeric == Decimal("1.000000000000")
