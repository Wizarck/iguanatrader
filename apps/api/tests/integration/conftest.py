"""Integration test fixtures for the FastAPI auth surface.

Each test function gets:

* A fresh on-disk SQLite engine (per-test ``tmp_path``) overriding the
  module-level :func:`iguanatrader.api.deps._get_engine` cache so route
  handlers hit the test DB.
* The slice-3 tenant + append-only listeners registered (auto-undone
  on test exit).
* A fixed ``IGUANATRADER_JWT_SECRET`` so encode/decode is deterministic.
* The slowapi limiter's storage reset between tests (otherwise
  test_login_rate_limited_after_5_attempts pollutes downstream tests).
* An :class:`httpx.AsyncClient` wired to the FastAPI app via
  :class:`httpx.ASGITransport`, with ``base_url="https://test"`` so the
  ``Secure``-flagged cookie travels back on subsequent requests
  (httpx enforces RFC 6265 — Secure cookies are only sent over HTTPS,
  even though ASGITransport is in-memory and doesn't do TLS).
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from iguanatrader.api import deps as api_deps
from iguanatrader.api.app import create_app
from iguanatrader.api.auth import hash_password
from iguanatrader.api.limiting import limiter
from iguanatrader.persistence import (
    Tenant,
    User,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base

# Same Windows event-loop quirk as the persistence conftest.
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

#: Plaintext password seeded for the canonical fixture user. Tests refer
#: to this constant rather than the literal string so any future rename
#: is grep-safe.
SEEDED_PLAINTEXT_PASSWORD: str = "correct horse battery staple"
SEEDED_USER_EMAIL: str = "alice@example.com"
SEEDED_TENANT_NAME: str = "alice-trading"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_JWT_SECRET", "x" * 64)


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    """Drop slowapi's in-memory store between tests."""
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()


@pytest.fixture(autouse=True)
def _register_listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    db_path = tmp_path / "ig_auth_test.db"
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


@pytest.fixture
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    eng = engine_factory(db_url)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def schema_session_factory(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Empty schema created from ``Base.metadata`` (NOT via Alembic — the
    integration suite is schema-shape-tested by the persistence package).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield session_factory(engine)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def app_with_overrides(
    engine: AsyncEngine,
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Any]:
    """FastAPI app with the engine + session-factory caches overridden.

    :func:`iguanatrader.api.deps._get_engine` and
    :func:`_get_session_factory` are :func:`functools.lru_cache`-wrapped;
    rather than fight the cache we override the FastAPI ``Depends``
    target via the ``dependency_overrides`` dict.
    """
    app = create_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with schema_session_factory() as s:
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


@pytest.fixture
async def seeded_tenant_user(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    """Insert one ``Tenant`` + one ``User`` (Argon2id hash of the known plaintext).

    Returns the inserted ``user_id`` and ``tenant_id`` as ``str``s for
    test assertions. Uses ``role='tenant_user'`` to match the
    canonical single-seat-per-tenant model (per
    ``docs/personas-jtbd.md`` §RBAC Matrix refined 2026-05-05).
    """
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    pw_hash = hash_password(SEEDED_PLAINTEXT_PASSWORD)

    async with schema_session_factory() as s:
        s.add(Tenant(id=tenant_id, name=SEEDED_TENANT_NAME, feature_flags={}))
        s.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=SEEDED_USER_EMAIL,
                password_hash=pw_hash,
                role="tenant_user",
            )
        )
        await s.commit()

    return {"user_id": user_id, "tenant_id": tenant_id, "email": SEEDED_USER_EMAIL}
