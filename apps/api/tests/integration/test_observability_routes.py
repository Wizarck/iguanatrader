"""Integration tests for ``GET /api/v1/costs/*`` (FR42 + slice-5 contract).

Test matrix (per task 7.6):

- ``GET /costs/summary`` returns tenant-scoped totals.
- ``GET /costs/by-provider`` returns Anthropic vs OpenAI breakdown.
- ``GET /costs/per-trade`` returns FR42 ratio (zero until slice T1 lands).
- All endpoints return RFC 7807 401 on auth failure.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from httpx import AsyncClient
from iguanatrader.contexts.observability.models import ApiCostEvent
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession


async def _seed_cost_event(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    *,
    provider: str,
    model: str,
    cost_usd: Decimal,
) -> None:
    async with with_tenant_context(tenant_id), session_factory() as s:
        s.add(
            ApiCostEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                tokens_input=100,
                tokens_output=200,
                cost_usd=cost_usd,
                cached=False,
                metadata_json={},
            )
        )
        await s.commit()


async def test_costs_summary_unauthenticated_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/costs/summary")
    assert resp.status_code == 401


async def test_costs_by_provider_unauthenticated_returns_401(
    client: AsyncClient,
) -> None:
    resp = await client.get("/api/v1/costs/by-provider")
    assert resp.status_code == 401


async def test_costs_per_trade_unauthenticated_returns_401(
    client: AsyncClient,
) -> None:
    resp = await client.get("/api/v1/costs/per-trade")
    assert resp.status_code == 401


async def test_costs_summary_tenant_scoped_totals(
    client: AsyncClient,
    schema_session_factory: async_sessionmaker[AsyncSession],
    seeded_tenant_user: dict[str, str],
) -> None:
    from .conftest import SEEDED_PLAINTEXT_PASSWORD, SEEDED_USER_EMAIL

    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    await _seed_cost_event(
        schema_session_factory,
        tenant_id,
        provider="anthropic",
        model="claude-3-5-sonnet",
        cost_usd=Decimal("3.50"),
    )

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": SEEDED_USER_EMAIL, "password": SEEDED_PLAINTEXT_PASSWORD},
    )
    assert login.status_code == 200

    resp = await client.get("/api/v1/costs/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == seeded_tenant_user["tenant_id"]
    assert Decimal(body["total_cost_usd"]) == Decimal("3.50")
    assert body["total_calls"] == 1


async def test_costs_by_provider_breakdown(
    client: AsyncClient,
    schema_session_factory: async_sessionmaker[AsyncSession],
    seeded_tenant_user: dict[str, str],
) -> None:
    from .conftest import SEEDED_PLAINTEXT_PASSWORD, SEEDED_USER_EMAIL

    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    await _seed_cost_event(
        schema_session_factory,
        tenant_id,
        provider="anthropic",
        model="claude-3-5-sonnet",
        cost_usd=Decimal("3.00"),
    )
    await _seed_cost_event(
        schema_session_factory,
        tenant_id,
        provider="openai",
        model="gpt-4o-mini",
        cost_usd=Decimal("0.50"),
    )

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": SEEDED_USER_EMAIL, "password": SEEDED_PLAINTEXT_PASSWORD},
    )
    assert login.status_code == 200

    resp = await client.get("/api/v1/costs/by-provider")
    assert resp.status_code == 200
    body = resp.json()
    rows_by_provider = {r["provider"]: r for r in body["breakdown"]}
    assert Decimal(rows_by_provider["anthropic"]["cost_usd"]) == Decimal("3.00")
    assert Decimal(rows_by_provider["openai"]["cost_usd"]) == Decimal("0.50")


async def test_costs_per_trade_returns_zero_until_t1(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
) -> None:
    from .conftest import SEEDED_PLAINTEXT_PASSWORD, SEEDED_USER_EMAIL

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": SEEDED_USER_EMAIL, "password": SEEDED_PLAINTEXT_PASSWORD},
    )
    assert login.status_code == 200

    resp = await client.get("/api/v1/costs/per-trade")
    assert resp.status_code == 200
    body = resp.json()
    assert body["closed_trades_count"] == 0
    assert body["cost_per_trade_usd"] is None
