"""Integration tests for ``/api/v1/trades`` GET endpoints (slice trades-read-endpoints).

Mirror of :mod:`apps.api.tests.integration.test_approval_routes` —
cookie-driven JWT auth + ASGI transport + tenant-scoped seeds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from iguanatrader.api import deps as api_deps
from iguanatrader.api.app import create_app
from iguanatrader.api.auth import encode_jwt, hash_password
from iguanatrader.api.deps import COOKIE_NAME
from iguanatrader.contexts.trading.models import (
    Fill,
    Order,
    StrategyConfig,
    Trade,
    TradeProposal,
)
from iguanatrader.persistence import (
    Tenant,
    User,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_JWT_SECRET", "x" * 64)


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    db_path = tmp_path / "ig_trade_routes.db"
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


@pytest.fixture
async def seed(sf: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    tid = uuid4()
    uid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t-trades", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            User(
                id=uid,
                tenant_id=tid,
                email="trader@example.com",
                password_hash=hash_password("pw"),
                role="tenant_user",
            )
        )
        await s.commit()
    return {"tenant_id": tid, "user_id": uid}


@pytest.fixture
async def app_with_overrides(
    engine: AsyncEngine,
    sf: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Any]:
    app = create_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with sf() as s:
            yield s

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def client(app_with_overrides: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_with_overrides)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


def _login_cookie(user_id: str, tenant_id: str, role: str = "tenant_user") -> str:
    import time

    return encode_jwt(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": role,
            "login_at": int(time.time()),
        },
        exp_seconds=3600,
    )


async def _seed_trade(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str = "AAPL",
    created_offset_seconds: int = 0,
) -> dict[str, UUID]:
    """Seed proposal + trade + order + 1 fill; return the ids."""
    proposal_id = uuid4()
    trade_id = uuid4()
    order_id = uuid4()
    fill_id = uuid4()
    strategy_config_id = uuid4()
    base = datetime.now(UTC)
    # Flush after each add(): SQLAlchemy 2.x's INSERTMANYVALUES + RETURNING
    # path on aiosqlite can batch sibling inserts before their parent FK
    # is visible. One-row-at-a-time flushing sidesteps the race.
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            StrategyConfig(
                id=strategy_config_id,
                tenant_id=tenant_id,
                strategy_kind="donchian_atr",
                symbol=symbol,
                params={"lookback": 20},
                enabled=True,
            )
        )
        await s.flush()
        s.add(
            TradeProposal(
                id=proposal_id,
                tenant_id=tenant_id,
                strategy_config_id=strategy_config_id,
                research_brief_id=None,
                correlation_id=uuid4(),
                symbol=symbol,
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("100"),
                stop_price=Decimal("95"),
                reasoning={"why": "test"},
                mode="paper",
            )
        )
        await s.flush()
        s.add(
            Trade(
                id=trade_id,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol=symbol,
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state="open",
                opened_at=base,
                created_at=base + timedelta(seconds=created_offset_seconds),
            )
        )
        await s.flush()
        s.add(
            Order(
                id=order_id,
                tenant_id=tenant_id,
                trade_id=trade_id,
                broker="ibkr",
                broker_order_id=f"IB-{order_id}",
                order_type="market",
                side="buy",
                quantity=Decimal("10"),
                state="filled",
                submitted_at=base,
            )
        )
        await s.flush()
        s.add(
            Fill(
                id=fill_id,
                tenant_id=tenant_id,
                order_id=order_id,
                quantity_filled=Decimal("10"),
                fill_price=Decimal("100.50"),
                commission=Decimal("0.01"),
                commission_currency="USD",
                filled_at=base,
                broker_fill_id=f"FILL-{fill_id}",
            )
        )
        await s.commit()
    return {
        "proposal_id": proposal_id,
        "trade_id": trade_id,
        "order_id": order_id,
        "fill_id": fill_id,
    }


@pytest.mark.asyncio
async def test_list_trades_returns_tenant_trades_sorted_desc(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, Any],
) -> None:
    tid: UUID = seed["tenant_id"]
    uid: UUID = seed["user_id"]
    older = await _seed_trade(sf, tenant_id=tid, symbol="AAPL", created_offset_seconds=0)
    newer = await _seed_trade(sf, tenant_id=tid, symbol="MSFT", created_offset_seconds=60)

    cookie = _login_cookie(str(uid), str(tid))
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get(
        "/api/v1/trades",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    # Newer trade first.
    assert body["items"][0]["id"] == str(newer["trade_id"])
    assert body["items"][1]["id"] == str(older["trade_id"])


@pytest.mark.asyncio
async def test_list_trades_empty_for_new_tenant(
    client: AsyncClient,
    seed: dict[str, Any],
) -> None:
    tid: UUID = seed["tenant_id"]
    uid: UUID = seed["user_id"]
    cookie = _login_cookie(str(uid), str(tid))
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/trades")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_get_trade_returns_200_on_hit(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, Any],
) -> None:
    tid: UUID = seed["tenant_id"]
    uid: UUID = seed["user_id"]
    ids = await _seed_trade(sf, tenant_id=tid)
    cookie = _login_cookie(str(uid), str(tid))
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get(
        f"/api/v1/trades/{ids['trade_id']}",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(ids["trade_id"])
    assert body["symbol"] == "AAPL"
    assert body["side"] == "buy"


@pytest.mark.asyncio
async def test_get_trade_returns_404_on_miss(
    client: AsyncClient,
    seed: dict[str, Any],
) -> None:
    uid: UUID = seed["user_id"]
    tid: UUID = seed["tenant_id"]
    cookie = _login_cookie(str(uid), str(tid))
    client.cookies.set(COOKIE_NAME, cookie)
    bogus = uuid4()
    resp = await client.get(
        f"/api/v1/trades/{bogus}",
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:not-found"
    assert str(bogus) in body["detail"]


@pytest.mark.asyncio
async def test_list_trade_fills_joins_via_orders(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, Any],
) -> None:
    tid: UUID = seed["tenant_id"]
    uid: UUID = seed["user_id"]
    ids = await _seed_trade(sf, tenant_id=tid)
    cookie = _login_cookie(str(uid), str(tid))
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get(
        f"/api/v1/trades/{ids['trade_id']}/fills",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    fill = body["items"][0]
    assert fill["order_id"] == str(ids["order_id"])
    assert Decimal(fill["quantity_filled"]) == Decimal("10")
    assert Decimal(fill["fill_price"]) == Decimal("100.50")
