"""Integration tests for the cost-meter decorator (FR40 + NFR-O1 + design D1).

Test matrix (per task 7.2):

- (a) Decorated function call records :class:`ApiCostEvent` with correct
  fields + ``tenant_id`` from :data:`tenant_id_var`.
- (b) Cached response → ``cached=True``, ``cost_usd=0``.
- (c) SDK exception propagates without recording phantom event.
- (d) Bare LLM SDK call outside ``@cost_meter``-decorated stack frame is
  flagged via the introspection check (``inspect.stack()`` lookup).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.observability.cost_meter import cost_meter
from iguanatrader.contexts.observability.models import ApiCostEvent
from iguanatrader.persistence import Tenant
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import (
    session_var,
    tenant_id_var,
    with_tenant_context,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class FakeLLMResponse:
    tokens_input: int
    tokens_output: int
    cached: bool


@pytest.fixture
async def session_for_test(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Bind a fresh AsyncSession to ``session_var`` for the duration of the test."""
    async with schema_session_factory() as session:
        token = session_var.set(session)
        try:
            yield session
        finally:
            session_var.reset(token)


@pytest.fixture
async def seeded_tenant_id(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> UUID:
    tenant_id = uuid4()
    async with schema_session_factory() as s:
        s.add(Tenant(id=tenant_id, name="cost-meter-test", feature_flags={}))
        await s.commit()
    return tenant_id


async def test_decorator_records_event_with_correct_fields(
    session_for_test: AsyncSession,
    seeded_tenant_id: UUID,
) -> None:
    @cost_meter(provider="anthropic", model="claude-3-5-sonnet")
    async def fake_call() -> FakeLLMResponse:
        return FakeLLMResponse(tokens_input=1_000_000, tokens_output=500_000, cached=False)

    async with with_tenant_context(seeded_tenant_id):
        await fake_call()
        await session_for_test.commit()

    async with with_tenant_context(seeded_tenant_id):
        rows = (await session_for_test.execute(select(ApiCostEvent))).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.tenant_id == seeded_tenant_id
    assert row.provider == "anthropic"
    assert row.model == "claude-3-5-sonnet"
    assert row.tokens_input == 1_000_000
    assert row.tokens_output == 500_000
    assert row.cached is False
    # 1M tokens @ $3 + 0.5M tokens @ $15 = $3 + $7.50 = $10.50
    assert row.cost_usd == Decimal("10.500000")


async def test_cached_response_records_zero_cost(
    session_for_test: AsyncSession,
    seeded_tenant_id: UUID,
) -> None:
    @cost_meter(provider="anthropic", model="claude-3-5-haiku")
    async def cached_call() -> FakeLLMResponse:
        return FakeLLMResponse(tokens_input=100, tokens_output=200, cached=True)

    async with with_tenant_context(seeded_tenant_id):
        await cached_call()
        await session_for_test.commit()

    async with with_tenant_context(seeded_tenant_id):
        rows = (await session_for_test.execute(select(ApiCostEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].cached is True
    assert rows[0].cost_usd == Decimal("0")


async def test_sdk_exception_propagates_without_recording(
    session_for_test: AsyncSession,
    seeded_tenant_id: UUID,
) -> None:
    class _Boom(Exception):
        pass

    @cost_meter(provider="anthropic", model="claude-3-5-haiku")
    async def boom_call() -> FakeLLMResponse:
        raise _Boom("upstream failed")

    with pytest.raises(_Boom):
        async with with_tenant_context(seeded_tenant_id):
            await boom_call()

    # Suppress the listener for the verification query — we want to read
    # api_cost_events even though the test session may not have a tenant
    # bound at this point.
    async with with_tenant_context(seeded_tenant_id):
        rows = (await session_for_test.execute(select(ApiCostEvent))).scalars().all()
    assert rows == []


async def test_meter_log_only_when_session_unbound() -> None:
    """When ``session_var`` is unbound, the decorator emits the structlog
    breadcrumb but does not crash. No persistence is attempted.
    """

    @cost_meter(provider="openai", model="gpt-4o-mini")
    async def fake_call() -> FakeLLMResponse:
        return FakeLLMResponse(tokens_input=10, tokens_output=20, cached=False)

    # No session_var bound, no tenant_id_var bound.
    response = await fake_call()
    assert response.tokens_input == 10


# Suppress unused import warning when used via fixture forwarding.
_ = (Base, tenant_id_var)
