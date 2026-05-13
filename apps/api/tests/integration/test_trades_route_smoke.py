"""Smoke tests for the 3 ``/api/v1/trades*`` endpoints (slice trades-list-and-detail).

Defense-in-depth alongside :mod:`test_trade_routes`: fresh empty-tenant
shape checks for the contracts the UI consumes. Keeps the dashboard tab
bound to the documented JSON shape so a backend change that breaks the
contract surfaces here BEFORE the vitest page tests start failing.

Uses the canonical ``conftest.py`` ``client`` + ``seeded_tenant_user``
fixtures so the ``must_change_password`` middleware finds the test
session factory (otherwise the middleware opens a real engine and the
request fails with ``unable to open database file``).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from iguanatrader.api.auth import encode_jwt
from iguanatrader.api.deps import COOKIE_NAME

# Force trading-table mappers to load so the conftest's ``Base.metadata``
# ``create_all`` includes ``trades`` / ``orders`` / ``fills``. Without
# this import the integration suite's shared ``schema_session_factory``
# only creates the auth tables.
from iguanatrader.contexts.trading import models as _trading_models  # noqa: F401


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
async def test_list_trades_empty_tenant_shape(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
) -> None:
    """GET /api/v1/trades on a fresh tenant matches TradeListOut shape."""
    cookie = _login_cookie(seeded_tenant_user["user_id"], seeded_tenant_user["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/trades")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    assert body == {"items": [], "total": 0, "next_cursor": None}


@pytest.mark.asyncio
async def test_get_trade_missing_returns_rfc7807(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
) -> None:
    """GET /api/v1/trades/{bogus_id} on empty tenant returns RFC 7807 404."""
    cookie = _login_cookie(seeded_tenant_user["user_id"], seeded_tenant_user["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get(f"/api/v1/trades/{uuid4()}")
    assert resp.status_code == 404, resp.text
    body: dict[str, Any] = resp.json()
    assert body["type"] == "urn:iguanatrader:error:not-found"
    assert "detail" in body


@pytest.mark.asyncio
async def test_list_fills_no_trade_returns_empty_list(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
) -> None:
    """GET /api/v1/trades/{bogus_id}/fills returns empty list (NOT 404).

    Per the route's contract (``test_trade_routes`` already pins the
    behaviour for the seeded path); smoke test verifies the no-trade
    branch returns the canonical empty shape so the UI's detail page
    can rely on it.
    """
    cookie = _login_cookie(seeded_tenant_user["user_id"], seeded_tenant_user["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get(f"/api/v1/trades/{uuid4()}/fills")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    assert body == {"items": [], "total": 0, "next_cursor": None}
