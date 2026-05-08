"""Integration tests for ``/settings/feature-flags`` (slice R6).

GET returns the current feature_flags dict + PUT whitelisted keys
(only ``hindsight_recall_enabled`` in v1). Unknown keys are rejected
by Pydantic ``extra='forbid'`` -> 400.
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
    db_path = tmp_path / "ig_settings.db"
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
        s.add(Tenant(id=tid, name="t-settings", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            User(
                id=uid,
                tenant_id=tid,
                email="settings@example.com",
                password_hash=hash_password("pw"),
                role="tenant_user",
            )
        )
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
    import time

    return encode_jwt(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": "tenant_user",
            "login_at": int(time.time()),
        },
        exp_seconds=3600,
    )


@pytest.mark.asyncio
async def test_get_feature_flags_returns_default_off(
    client: AsyncClient,
    seed: dict[str, Any],
) -> None:
    tid: UUID = seed["tenant_id"]
    uid: UUID = seed["user_id"]
    cookie = _login_cookie(str(uid), str(tid))
    resp = await client.get(
        "/api/v1/settings/feature-flags",
        cookies={COOKIE_NAME: cookie},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"hindsight_recall_enabled": False}


@pytest.mark.asyncio
async def test_put_feature_flags_persists_toggle(
    client: AsyncClient,
    seed: dict[str, Any],
) -> None:
    tid: UUID = seed["tenant_id"]
    uid: UUID = seed["user_id"]
    cookie = _login_cookie(str(uid), str(tid))
    resp = await client.put(
        "/api/v1/settings/feature-flags",
        cookies={COOKIE_NAME: cookie},
        json={"hindsight_recall_enabled": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["hindsight_recall_enabled"] is True

    # GET reflects the change.
    resp2 = await client.get(
        "/api/v1/settings/feature-flags",
        cookies={COOKIE_NAME: cookie},
    )
    assert resp2.json()["hindsight_recall_enabled"] is True


@pytest.mark.asyncio
async def test_put_feature_flags_rejects_unknown_key(
    client: AsyncClient,
    seed: dict[str, Any],
) -> None:
    tid: UUID = seed["tenant_id"]
    uid: UUID = seed["user_id"]
    cookie = _login_cookie(str(uid), str(tid))
    resp = await client.put(
        "/api/v1/settings/feature-flags",
        cookies={COOKIE_NAME: cookie},
        json={"hindsight_recall_enabled": True, "made_up_key": "yes"},
    )
    assert resp.status_code == 422, resp.text  # Pydantic validation error
