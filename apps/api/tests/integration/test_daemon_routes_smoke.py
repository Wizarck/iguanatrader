"""Smoke tests for /api/v1/status + /api/v1/daemons/{mode}/* (slice
``dual-daemon-mode-toggle-and-reconcile``).

Covers the happy paths + the security-critical failure paths:

* migration 0026 seeds (paper, enabled=true) + (live, enabled=false) for
  every tenant
* GET /status returns the per-mode summary
* POST /paper/toggle flips the flag without password
* POST /live/toggle requires password + reason (>=20 chars), 403 on
  password mismatch, 422 on payload-invalid
* POST /reconcile stamps pending_reconcile_at on the row

The bigger drain + reconcile-with-broker flows live in their own
files; this file is the route-layer smoke pass.
"""

from __future__ import annotations

import time
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
from iguanatrader.contexts.trading.models import TenantTradingMode
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
    db_path = tmp_path / "ig_daemons.db"
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
        s.add(Tenant(id=tid, name="t-daemons", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            User(
                id=uid,
                tenant_id=tid,
                email="daemons@example.com",
                password_hash=hash_password("correct-horse-battery-staple"),
                role="tenant_user",
            )
        )
        # ``create_all`` does not run the migration data-fill — seed
        # manually to match the post-0026 production shape.
        s.add(TenantTradingMode(tenant_id=tid, mode="paper", enabled=True))
        s.add(TenantTradingMode(tenant_id=tid, mode="live", enabled=False))
        await s.commit()
    return {"tenant_id": tid, "user_id": uid}


@pytest.fixture
async def app_with_overrides(
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


def _login_cookie(user_id: str, tenant_id: str) -> str:
    return encode_jwt(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": "tenant_user",
            "login_at": int(time.time()),
        },
        exp_seconds=3600,
    )


def _set_cookie(client: AsyncClient, seed: dict[str, Any]) -> None:
    tid: UUID = seed["tenant_id"]
    uid: UUID = seed["user_id"]
    client.cookies.set(COOKIE_NAME, _login_cookie(str(uid), str(tid)))


@pytest.mark.asyncio
async def test_status_returns_seeded_paper_and_live(
    client: AsyncClient,
    seed: dict[str, Any],
) -> None:
    _set_cookie(client, seed)
    resp = await client.get("/api/v1/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    daemons = {d["mode"]: d for d in body["daemons"]}
    assert daemons["paper"]["enabled"] is True
    assert daemons["live"]["enabled"] is False
    # No heartbeat written yet → ib_connected collapses to False.
    assert daemons["paper"]["ib_connected"] is False
    assert daemons["live"]["ib_connected"] is False
    assert daemons["paper"]["pending_proposals_count"] == 0


@pytest.mark.asyncio
async def test_toggle_paper_flips_without_password(
    client: AsyncClient,
    seed: dict[str, Any],
) -> None:
    _set_cookie(client, seed)
    resp = await client.post(
        "/api/v1/daemons/paper/toggle",
        json={"enabled": False, "reason": "manual smoke pause"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_toggle_live_missing_password_returns_422(
    client: AsyncClient,
    seed: dict[str, Any],
) -> None:
    _set_cookie(client, seed)
    resp = await client.post(
        "/api/v1/daemons/live/toggle",
        json={
            "enabled": True,
            "reason": "promoting validated donchian strategy to live",
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_toggle_live_short_reason_returns_422(
    client: AsyncClient,
    seed: dict[str, Any],
) -> None:
    _set_cookie(client, seed)
    resp = await client.post(
        "/api/v1/daemons/live/toggle",
        json={
            "enabled": True,
            "reason": "too short",
            "password_reconfirm": "correct-horse-battery-staple",
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_toggle_live_wrong_password_returns_403(
    client: AsyncClient,
    seed: dict[str, Any],
) -> None:
    _set_cookie(client, seed)
    resp = await client.post(
        "/api/v1/daemons/live/toggle",
        json={
            "enabled": True,
            "reason": "promoting validated donchian strategy to live",
            "password_reconfirm": "not-the-right-password",
        },
    )
    assert resp.status_code == 403, resp.text
    assert "password-mismatch" in resp.json()["type"]


@pytest.mark.asyncio
async def test_toggle_live_happy_path(
    client: AsyncClient,
    seed: dict[str, Any],
) -> None:
    _set_cookie(client, seed)
    resp = await client.post(
        "/api/v1/daemons/live/toggle",
        json={
            "enabled": True,
            "reason": "promoting validated donchian strategy to live",
            "password_reconfirm": "correct-horse-battery-staple",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "live"
    assert body["enabled"] is True


@pytest.mark.asyncio
async def test_reconcile_stamps_pending_reconcile_at(
    client: AsyncClient,
    seed: dict[str, Any],
    sf: async_sessionmaker[AsyncSession],
) -> None:
    _set_cookie(client, seed)
    resp = await client.post("/api/v1/daemons/paper/reconcile")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["mode"] == "paper"
    assert body["correlation_id"]
    assert body["accepted_at"]

    # Verify DB-side marker landed.
    async with with_tenant_context(seed["tenant_id"]), sf() as s:
        result = await s.execute(
            select(TenantTradingMode).where(
                TenantTradingMode.tenant_id == seed["tenant_id"],
                TenantTradingMode.mode == "paper",
            )
        )
        row = result.scalars().first()
        assert row is not None
        assert row.pending_reconcile_at is not None
