"""Smoke test for the ``/healthz`` liveness route.

The route exists outside the ``/api/v1`` prefix so docker / compose /
k8s healthchecks can probe it without knowing the API versioning scheme.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from iguanatrader.api.app import create_app


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_JWT_SECRET", "x" * 64)


@pytest.mark.asyncio
async def test_healthz_returns_ok() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
