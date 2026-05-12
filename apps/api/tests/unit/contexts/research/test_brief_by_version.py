"""Unit tests for :meth:`ResearchRepository.brief_by_symbol_and_version`.

Slice ``research-brief-by-version-endpoint``. Asserts the new repository
method returns the exact brief at the requested version + ``None`` for
absent versions, honouring the ``UNIQUE (tenant_id, symbol_universe_id,
version)`` constraint.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.research.models import WatchlistConfig
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _seed_watchlist(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    universe_id: UUID,
) -> UUID:
    watchlist_id = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            WatchlistConfig(
                id=watchlist_id,
                tenant_id=tenant_id,
                symbol_universe_id=universe_id,
                tier="A",
                methodology="three_pillar",
                methodology_params=None,
                brief_refresh_schedule="weekly",
                brief_refresh_cron=None,
                enabled=True,
            )
        )
        await s.commit()
    return watchlist_id


@pytest.mark.asyncio
async def test_returns_brief_at_requested_version(
    session_factory_fx: async_sessionmaker[AsyncSession],
    seeded_world: dict[str, Any],
    repository: ResearchRepository,
) -> None:
    tenant_id = UUID(str(seeded_world["tenant_id"]))
    universe_id = UUID(str(seeded_world["universe_id"]))
    watchlist_id = await _seed_watchlist(
        session_factory_fx, tenant_id=tenant_id, universe_id=universe_id
    )

    # Seed v1 + v2.
    for version in (1, 2):
        async with with_tenant_context(tenant_id), session_factory_fx() as s:
            token = session_var.set(s)
            try:
                await repository.insert_brief(
                    symbol_universe_id=universe_id,
                    watchlist_config_id=watchlist_id,
                    version=version,
                    methodology="three_pillar",
                    thesis_text=f"thesis v{version}",
                    score_overall=None,
                    score_components=None,
                    citations=[],
                    audit_trail=[],
                    llm_provider="mock",
                    llm_model="mock-001",
                    llm_input_tokens=0,
                    llm_output_tokens=0,
                )
                await s.commit()
            finally:
                session_var.reset(token)

    # Read v1 + v2 individually + assert missing v99 → None.
    async with with_tenant_context(tenant_id), session_factory_fx() as s:
        token = session_var.set(s)
        try:
            v1 = await repository.brief_by_symbol_and_version("AAPL", 1)
            v2 = await repository.brief_by_symbol_and_version("AAPL", 2)
            v99 = await repository.brief_by_symbol_and_version("AAPL", 99)
        finally:
            session_var.reset(token)

    assert v1 is not None and v1.version == 1
    assert v1.thesis_text == "thesis v1"
    assert v2 is not None and v2.version == 2
    assert v2.thesis_text == "thesis v2"
    assert v99 is None


@pytest.mark.asyncio
async def test_returns_none_for_unknown_symbol(
    session_factory_fx: async_sessionmaker[AsyncSession],
    seeded_world: dict[str, Any],
    repository: ResearchRepository,
) -> None:
    tenant_id = UUID(str(seeded_world["tenant_id"]))
    async with with_tenant_context(tenant_id), session_factory_fx() as s:
        token = session_var.set(s)
        try:
            result = await repository.brief_by_symbol_and_version("ZZZZ", 1)
        finally:
            session_var.reset(token)
    assert result is None
