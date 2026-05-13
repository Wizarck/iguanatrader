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


#: Endpoints that legitimately still raise 501 + Problem JSON until their
#: owning slice lands. Trades + portfolio + strategies were wired by
#: their respective slices (see ``test_trade_routes.py``,
#: ``test_portfolio_routes.py``, ``test_strategies_routes.py``).
#: ``GET /proposals/{id}`` is also wired (returns 404 on miss); the
#: only remaining stub is the list endpoint, owned by the future
#: ``proposals-list-endpoint`` slice.
STUB_ENDPOINTS: list[tuple[str, str]] = [
    ("GET", "/api/v1/proposals"),
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
