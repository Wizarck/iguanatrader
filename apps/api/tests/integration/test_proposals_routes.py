"""Integration tests for ``GET /api/v1/proposals`` (slice proposals-list-endpoint).

Three cases per proposal §Tests:

1. ``GET /proposals`` empty tenant → ``{items: [], total: 0, next_cursor: null}``.
2. ``GET /proposals`` with 2 seeded proposals at different ``created_at`` →
   newest first (``created_at DESC``).
3. ``GET /proposals`` for tenant B cannot see tenant A's proposals
   (slice-3 ``tenant_listener`` enforces isolation on SELECT).

Mirror of :mod:`apps.api.tests.integration.test_strategies_routes` —
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

# Force trading-table mappers to load so the per-test
# ``Base.metadata.create_all`` includes ``trade_proposals``. Without
# this import the schema build only emits the auth tables.
from iguanatrader.contexts.trading import models as _trading_models  # noqa: F401
from iguanatrader.contexts.trading.models import StrategyConfig, TradeProposal
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
    db_path = tmp_path / "ig_proposals_routes.db"
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


async def _seed_proposal(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str,
    created_at: datetime,
) -> UUID:
    """Insert a :class:`StrategyConfig` + :class:`TradeProposal` for ``tenant_id``.

    The proposal's ``strategy_config_id`` FK is enforced by SQLite
    (``PRAGMA foreign_keys=ON`` set in the connect listener), so we seed
    a config row first.
    """
    proposal_id = uuid4()
    strategy_config_id = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            StrategyConfig(
                id=strategy_config_id,
                tenant_id=tenant_id,
                strategy_kind="donchian_atr",
                symbol=symbol,
                params={},
                enabled=True,
                version=1,
            )
        )
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
                stop_price=Decimal("90"),
                reasoning={"why": "test"},
                mode="paper",
                created_at=created_at,
            )
        )
        await s.commit()
    return proposal_id


@pytest.fixture
async def seed(sf: async_sessionmaker[AsyncSession]) -> dict[str, UUID]:
    return await _seed_tenant_user(sf, email="trader@example.com", tenant_name="t-proposals")


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


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_proposals_empty_tenant(
    client: AsyncClient,
    seed: dict[str, UUID],
) -> None:
    """Fresh tenant → ``{items: [], total: 0, next_cursor: null}``."""
    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/proposals")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    assert body == {"items": [], "total": 0, "next_cursor": None}


@pytest.mark.asyncio
async def test_list_proposals_returns_tenant_proposals_sorted_desc(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    """Two seeded proposals → newest (``created_at DESC``) first."""
    base = datetime.now(UTC)
    older_id = await _seed_proposal(
        sf,
        tenant_id=seed["tenant_id"],
        symbol="SPY",
        created_at=base - timedelta(minutes=10),
    )
    newer_id = await _seed_proposal(
        sf,
        tenant_id=seed["tenant_id"],
        symbol="QQQ",
        created_at=base,
    )

    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/proposals")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    assert body["total"] == 2
    assert body["next_cursor"] is None
    ids = [item["id"] for item in body["items"]]
    assert ids == [str(newer_id), str(older_id)], "expected newest first (created_at DESC)"
    assert body["items"][0]["symbol"] == "QQQ"
    assert body["items"][1]["symbol"] == "SPY"


@pytest.mark.asyncio
async def test_list_proposals_isolated_across_tenants(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
) -> None:
    """Tenant A's proposal invisible to tenant B (slice-3 ``tenant_listener``)."""
    a = await _seed_tenant_user(sf, email="alice@x.test", tenant_name="t-proposals-A")
    b = await _seed_tenant_user(sf, email="bob@x.test", tenant_name="t-proposals-B")
    await _seed_proposal(
        sf,
        tenant_id=a["tenant_id"],
        symbol="SPY",
        created_at=datetime.now(UTC),
    )

    cookie_b = _login_cookie(b["user_id"], b["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie_b)
    resp = await client.get("/api/v1/proposals")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    assert body == {"items": [], "total": 0, "next_cursor": None}


# ---------------------------------------------------------------------------
# Break-glass manual-approve guards (item 5b — explicit + pause-respecting)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_break_glass_approve_requires_explicit_confirm(
    client: AsyncClient,
    seed: dict[str, UUID],
) -> None:
    """Without ``?confirm=break-glass`` the override is refused (400) — it
    cannot be tripped by a generic client. The check fires before any
    proposal lookup, so a throwaway id is fine."""
    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.post(f"/api/v1/proposals/{uuid4()}/approve")
    assert resp.status_code == 400, resp.text
    assert "break-glass" in resp.text


@pytest.mark.asyncio
async def test_break_glass_approve_refused_when_paused(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    """With ``/lock`` active (``approvals_paused``) the override is refused
    (409) — it must not silently push a trade past the operator's pause."""
    proposal_id = await _seed_proposal(
        sf, tenant_id=seed["tenant_id"], symbol="SPY", created_at=datetime.now(UTC)
    )
    async with sf() as s:
        tenant = await s.get(Tenant, seed["tenant_id"])
        assert tenant is not None
        tenant.feature_flags = {"approvals_paused": True}
        await s.commit()

    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.post(f"/api/v1/proposals/{proposal_id}/approve?confirm=break-glass")
    assert resp.status_code == 409, resp.text
    assert "paused" in resp.text.lower()


@pytest.mark.asyncio
async def test_break_glass_approve_accepts_when_confirmed_and_not_paused(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit confirm + not paused → 202, and the ProposalApproved event
    is published exactly once with the right payload."""
    proposal_id = await _seed_proposal(
        sf, tenant_id=seed["tenant_id"], symbol="SPY", created_at=datetime.now(UTC)
    )

    published: list[Any] = []

    class _FakeBus:
        async def publish(self, event: Any) -> None:
            published.append(event)

    import iguanatrader.contexts.approval.bootstrap as bootstrap

    monkeypatch.setattr(bootstrap, "get_message_bus", lambda: _FakeBus())

    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.post(f"/api/v1/proposals/{proposal_id}/approve?confirm=break-glass")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["via"] == "break-glass"
    assert body["proposal_id"] == str(proposal_id)
    assert len(published) == 1
    assert published[0].proposal_id == proposal_id
