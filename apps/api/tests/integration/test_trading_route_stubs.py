"""Trading route stubs return 501 + RFC 7807 Problem until T4 lands.

Per design D6 + spec scenario "GET /api/v1/trades returns 501 with
canonical Problem body".

Each authenticated request to a stub endpoint must return:

* HTTP 501.
* ``Content-Type: application/problem+json``.
* Body ``type`` URI ``urn:iguanatrader:error:not-implemented``.
* Body ``detail`` referencing slice T4.

Reuses the slice-4 ``client`` + ``seeded_tenant_user`` fixtures (see
``apps/api/tests/integration/conftest.py``).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from .conftest import (
    SEEDED_PLAINTEXT_PASSWORD,
    SEEDED_USER_EMAIL,
)


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": SEEDED_USER_EMAIL, "password": SEEDED_PLAINTEXT_PASSWORD},
    )
    assert resp.status_code == 200, resp.text


STUB_ENDPOINTS: list[tuple[str, str]] = [
    ("GET", "/api/v1/trades"),
    ("GET", "/api/v1/trades/00000000-0000-0000-0000-000000000001"),
    ("GET", "/api/v1/trades/00000000-0000-0000-0000-000000000001/fills"),
    ("GET", "/api/v1/portfolio"),
    ("GET", "/api/v1/portfolio/positions"),
    ("GET", "/api/v1/portfolio/equity"),
    ("GET", "/api/v1/strategies"),
    ("GET", "/api/v1/strategies/SPY"),
    ("DELETE", "/api/v1/strategies/SPY"),
    ("GET", "/api/v1/proposals"),
    ("GET", "/api/v1/proposals/00000000-0000-0000-0000-000000000001"),
]


@pytest.mark.parametrize("method,path", STUB_ENDPOINTS)
async def test_trading_stub_returns_501_problem(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    method: str,
    path: str,
) -> None:
    """Authenticated client gets 501 + Problem JSON for every stub endpoint."""
    _ = seeded_tenant_user
    await _login(client)

    resp = await client.request(method, path)

    assert resp.status_code == 501, f"{method} {path} returned {resp.status_code}"
    assert resp.headers["content-type"].startswith("application/problem+json")

    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:not-implemented"
    assert body["status"] == 501
    assert body["title"] == "Feature Not Implemented"
    assert "T4" in body.get("detail", "")
    assert path in body.get("detail", "")


async def test_strategies_put_with_body_returns_501_problem(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
) -> None:
    """``PUT /strategies/{symbol}`` consumes a body but still 501s."""
    _ = seeded_tenant_user
    await _login(client)

    body = {
        "strategy_kind": "donchian_atr",
        "params": {"lookback": 20, "atr_mult": 2.0},
        "enabled": True,
    }
    resp = await client.put("/api/v1/strategies/SPY", json=body)

    assert resp.status_code == 501
    payload = resp.json()
    assert payload["type"] == "urn:iguanatrader:error:not-implemented"
    assert "T4" in payload["detail"]


async def test_openapi_surfaces_all_four_trading_route_prefixes(
    client: AsyncClient,
) -> None:
    """``/openapi.json`` advertises the trading route families.

    Slice-5 dynamic-discovery is meant to pick up the new modules
    without any edit to ``app.py`` / ``routes/__init__.py`` — a smoke
    test for that contract.
    """
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"].keys()
    expected_prefixes = [
        "/api/v1/trades",
        "/api/v1/portfolio",
        "/api/v1/strategies",
        "/api/v1/proposals",
    ]
    for prefix in expected_prefixes:
        assert any(p.startswith(prefix) for p in paths), f"missing {prefix} in OpenAPI"
