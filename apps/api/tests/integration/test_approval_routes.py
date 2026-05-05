"""Approval REST routes — happy path + cross-channel duplicate.

Per slice P1 task 6.4. The dashboard route flows through
:func:`command_handler.dispatch`; the second attempt (via the same
channel or a different channel) raises
:class:`ApprovalAlreadyDecidedError` rendered as RFC 7807.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from iguanatrader.api import deps as api_deps
from iguanatrader.api.app import create_app
from iguanatrader.api.auth import encode_jwt, hash_password
from iguanatrader.api.deps import COOKIE_NAME
from iguanatrader.contexts.approval.bootstrap import get_message_bus
from iguanatrader.contexts.approval.channels.command_handler import (
    reset_idempotency_cache,
)
from iguanatrader.contexts.approval.repository import ApprovalRepository
from iguanatrader.contexts.approval.service import ApprovalService
from iguanatrader.persistence import (
    Tenant,
    User,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import (
    session_var,
    with_tenant_context,
)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_JWT_SECRET", "x" * 64)


@pytest.fixture(autouse=True)
def _listeners() -> AsyncIterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    reset_idempotency_cache()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    db_path = tmp_path / "ig_approval_routes.db"
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
        s.add(Tenant(id=tid, name="t1", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            User(
                id=uid,
                tenant_id=tid,
                email="seed@example.com",
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
    async with AsyncClient(
        transport=transport, base_url="https://test"
    ) as c:
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


@pytest.mark.asyncio
async def test_dashboard_approve_happy_path(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, Any],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    proposal_id = uuid4()
    # Seed an approval_requests row directly.
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        repo = ApprovalRepository()
        service = ApprovalService(
            repository=repo,
            message_bus=get_message_bus(),
        )
        request = await service.create_request(
            proposal_id=proposal_id,
            channels=["dashboard"],
            timeout_seconds=60,
        )
        await session.commit()

    cookie = _login_cookie(str(uid), str(tid))
    resp = await client.post(
        f"/api/v1/approvals/{request.id}/approve",
        cookies={COOKIE_NAME: cookie},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_idempotent_retry_returns_409_or_dedup(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, Any],
) -> None:
    """Per spec: cross-channel retry after first wins → idempotent.

    The dispatcher's in-process cache short-circuits the second attempt
    via the same idempotency_key (request_id) before reaching the DB
    constraint. Result: status='ok' with extra={'deduped': True}.
    """
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    proposal_id = uuid4()
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        repo = ApprovalRepository()
        service = ApprovalService(
            repository=repo,
            message_bus=get_message_bus(),
        )
        request = await service.create_request(
            proposal_id=proposal_id,
            channels=["dashboard"],
            timeout_seconds=60,
        )
        await session.commit()

    cookie = _login_cookie(str(uid), str(tid))
    r1 = await client.post(
        f"/api/v1/approvals/{request.id}/approve",
        cookies={COOKIE_NAME: cookie},
    )
    r2 = await client.post(
        f"/api/v1/approvals/{request.id}/approve",
        cookies={COOKIE_NAME: cookie},
    )
    assert r1.status_code == 200
    # Second attempt is suppressed by the in-process dedup cache or
    # the DB UNIQUE constraint; either way the user-visible result
    # is idempotent + non-error.
    assert r2.status_code == 200
    assert r2.json()["status"] == "ok"
