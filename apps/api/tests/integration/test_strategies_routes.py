"""Integration tests for ``/api/v1/strategies*`` (slice trading-routes-portfolio-strategies-bodies).

Nine cases per proposal §Tests:

1. ``GET /strategies`` empty tenant → ``items=[]``.
2. ``GET /strategies`` with 2 configs → both rows.
3. ``GET /strategies/{symbol}`` no config → 404.
4. ``GET /strategies/{symbol}`` with single enabled config → row.
5. ``GET /strategies/{symbol}`` with two kinds → first (oldest) returned
   (doc'd v1 ambiguity).
6. ``PUT /strategies/{symbol}`` create → 200 + row persisted; ``PUT`` again
   bumps ``version``.
7. ``DELETE /strategies/{symbol}`` existing → all rows ``enabled=False``;
   row still in DB.
8. ``DELETE /strategies/{symbol}`` missing → 404.
9. Cross-tenant isolation.

Mirror of :mod:`apps.api.tests.integration.test_portfolio_routes` —
cookie-driven JWT auth + ASGI transport + tenant-scoped seeds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from iguanatrader.api import deps as api_deps
from iguanatrader.api.app import create_app
from iguanatrader.api.auth import encode_jwt, hash_password
from iguanatrader.api.deps import COOKIE_NAME
from iguanatrader.contexts.trading.models import StrategyConfig
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
from sqlalchemy import select
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
    db_path = tmp_path / "ig_strategies_routes.db"
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


async def _seed_tenant_user(
    sf: async_sessionmaker[AsyncSession],
    *,
    email: str,
    tenant_name: str,
) -> dict[str, UUID]:
    tid = uuid4()
    uid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=tenant_name, feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            User(
                id=uid,
                tenant_id=tid,
                email=email,
                password_hash=hash_password("pw"),
                role="tenant_user",
            )
        )
        await s.commit()
    return {"tenant_id": tid, "user_id": uid}


@pytest.fixture
async def seed(sf: async_sessionmaker[AsyncSession]) -> dict[str, UUID]:
    return await _seed_tenant_user(sf, email="trader@example.com", tenant_name="t-strategies")


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


def _login_cookie(user_id: UUID, tenant_id: UUID, role: str = "tenant_user") -> str:
    import time

    return encode_jwt(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "role": role,
            "login_at": int(time.time()),
        },
        exp_seconds=3600,
    )


async def _seed_strategy_config(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str,
    strategy_kind: str = "donchian_atr",
    params: dict[str, Any] | None = None,
    enabled: bool = True,
) -> UUID:
    config_id = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            StrategyConfig(
                id=config_id,
                tenant_id=tenant_id,
                strategy_kind=strategy_kind,
                symbol=symbol,
                params=params or {"lookback": 20, "atr_mult": 2.0},
                enabled=enabled,
                version=1,
            )
        )
        await s.commit()
    return config_id


# ---------------------------------------------------------------------------
# GET /strategies
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_strategies_empty_tenant_returns_empty_items(
    client: AsyncClient,
    seed: dict[str, UUID],
) -> None:
    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/strategies")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_strategies_returns_all_configs_sorted(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    # Seed out-of-order so the ASC sort can be verified.
    await _seed_strategy_config(sf, tenant_id=tid, symbol="SPY", strategy_kind="donchian_atr")
    await _seed_strategy_config(sf, tenant_id=tid, symbol="AAPL", strategy_kind="sma_cross")
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/strategies")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    # (symbol ASC, strategy_kind ASC) → AAPL/sma_cross then SPY/donchian_atr.
    assert body["items"][0]["symbol"] == "AAPL"
    assert body["items"][1]["symbol"] == "SPY"


# ---------------------------------------------------------------------------
# GET /strategies/{symbol}
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_strategy_by_symbol_returns_404_when_missing(
    client: AsyncClient,
    seed: dict[str, UUID],
) -> None:
    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/strategies/SPY")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:not-found"


@pytest.mark.asyncio
async def test_get_strategy_by_symbol_returns_single_enabled_config(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    config_id = await _seed_strategy_config(sf, tenant_id=tid, symbol="MSFT")
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/strategies/MSFT")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(config_id)
    assert body["symbol"] == "MSFT"
    assert body["enabled"] is True


@pytest.mark.asyncio
async def test_get_strategy_by_symbol_with_two_kinds_returns_oldest_enabled(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    """v1 ambiguity: backend supports multi-kind-per-symbol but GET-by-symbol
    resolves to the oldest enabled row. Multi-kind UI is v1.5."""
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    older_id = await _seed_strategy_config(
        sf, tenant_id=tid, symbol="TSLA", strategy_kind="donchian_atr"
    )
    await _seed_strategy_config(sf, tenant_id=tid, symbol="TSLA", strategy_kind="sma_cross")
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/strategies/TSLA")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Older config wins.
    assert body["id"] == str(older_id)
    assert body["strategy_kind"] == "donchian_atr"


# ---------------------------------------------------------------------------
# PUT /strategies/{symbol}
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_put_strategy_creates_then_bumps_version_on_second_put(
    client: AsyncClient,
    seed: dict[str, UUID],
) -> None:
    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    payload = {
        "strategy_kind": "donchian_atr",
        "params": {"lookback": 20, "atr_mult": 2.0},
        "enabled": True,
    }
    # First PUT — create.
    resp1 = await client.put(
        "/api/v1/strategies/NVDA",
        json=payload,
    )
    assert resp1.status_code == 200, resp1.text
    body1 = resp1.json()
    assert body1["symbol"] == "NVDA"
    assert body1["version"] == 1

    # Second PUT — update + version bump via before_update hook.
    payload2 = {
        **payload,
        "params": {"lookback": 30, "atr_mult": 1.5},
    }
    resp2 = await client.put(
        "/api/v1/strategies/NVDA",
        json=payload2,
    )
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    assert body2["id"] == body1["id"]  # Same row.
    assert body2["version"] == 2  # Bumped.
    assert body2["params"] == {"lookback": 30, "atr_mult": 1.5}


# ---------------------------------------------------------------------------
# DELETE /strategies/{symbol}
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delete_strategy_soft_disables_rows_without_deleting(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    config_id = await _seed_strategy_config(sf, tenant_id=tid, symbol="META")
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.delete("/api/v1/strategies/META")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "disabled", "symbol": "META"}

    # Row still in DB but enabled=False.
    async with with_tenant_context(tid), sf() as s:
        row = (
            await s.execute(select(StrategyConfig).where(StrategyConfig.id == config_id))
        ).scalar_one()
        assert row.enabled is False


@pytest.mark.asyncio
async def test_delete_strategy_returns_404_when_symbol_unknown(
    client: AsyncClient,
    seed: dict[str, UUID],
) -> None:
    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.delete("/api/v1/strategies/UNKNOWN")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:not-found"


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_strategies_isolated_across_tenants(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
) -> None:
    a = await _seed_tenant_user(sf, email="alice@x.test", tenant_name="t-strats-A")
    b = await _seed_tenant_user(sf, email="bob@x.test", tenant_name="t-strats-B")
    # Tenant A has one config; tenant B has none.
    await _seed_strategy_config(sf, tenant_id=a["tenant_id"], symbol="SPY")
    cookie_b = _login_cookie(b["user_id"], b["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie_b)
    # GET list for B is empty.
    resp_list = await client.get("/api/v1/strategies")
    assert resp_list.status_code == 200, resp_list.text
    assert resp_list.json()["items"] == []
    # GET by symbol for B is 404 (does not leak A's row).
    resp_get = await client.get("/api/v1/strategies/SPY")
    assert resp_get.status_code == 404
    # DELETE by symbol for B is 404 (does not affect A's row).
    resp_del = await client.delete("/api/v1/strategies/SPY")
    assert resp_del.status_code == 404
    # Confirm A's config still enabled.
    async with with_tenant_context(a["tenant_id"]), sf() as s:
        row = (
            await s.execute(select(StrategyConfig).where(StrategyConfig.symbol == "SPY"))
        ).scalar_one()
        assert row.enabled is True
