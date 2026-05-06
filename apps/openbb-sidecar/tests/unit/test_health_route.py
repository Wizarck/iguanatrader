"""Tests for the /health route.

Per task 2.7: pytest-asyncio + httpx ASGITransport client. Asserts the
response contract + the lazy-import readiness flag (mock openbb import
failure → openbb_loadable=false, status still "ok").
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from openbb_sidecar.adapters.openbb_facade import OpenBBFacade
from openbb_sidecar.main import create_app


@pytest.fixture
def reset_facade_cache() -> None:
    """Reset the cached import result so each test starts from cold."""
    OpenBBFacade._import_result = None
    OpenBBFacade._import_error = None


@pytest.mark.asyncio
async def test_health_returns_200_and_correct_shape(reset_facade_cache: None) -> None:
    """Happy path: openbb imports cleanly, health is 200 + loadable=true."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "openbb_loadable" in body
    assert "version" in body
    assert body["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_reports_loadable_false_when_openbb_import_fails(
    reset_facade_cache: None,
) -> None:
    """Mock openbb import to fail; assert health=200 + loadable=false + error populated."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "openbb":
            raise ImportError("mocked: openbb not installed")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    with patch("builtins.__import__", side_effect=fake_import):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    # Even with a non-loadable openbb, health is 200 (per design D8 — never 5xx).
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["openbb_loadable"] is False
    assert body["error"] is not None
    assert "openbb" in body["error"].lower()


@pytest.mark.asyncio
async def test_health_caches_import_result(reset_facade_cache: None) -> None:
    """Two consecutive /health calls only import openbb once (cached)."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    call_counts = {"openbb": 0}

    def counting_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "openbb":
            call_counts["openbb"] += 1
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    with patch("builtins.__import__", side_effect=counting_import):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/health")
            await client.get("/health")

    # The facade caches after first import; should be exactly 1 import.
    assert call_counts["openbb"] == 1
