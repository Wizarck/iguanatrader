"""Integration smoke for research route stubs (slice R1).

Covers spec scenarios under "Research route stubs render 501 RFC 7807
until R5 ships":

* ``GET /api/v1/research/briefs/{symbol}`` → 501 + Problem body with
  ``type=urn:iguanatrader:error:research-stub``.
* ``GET /api/v1/research/briefs/{brief_id}/audit-trail`` → same.
* ``GET /api/v1/research/facts/{symbol}`` → same.
* ``POST /api/v1/research/briefs/{symbol}/refresh`` → same.
* ``/openapi.json`` exposes ``BriefResponse`` + ``FactResponse`` +
  ``CitationDetail`` + ``AuditTrailEntry`` component schemas so the W1
  typegen pipeline can regenerate the typed client.

Uses the same app fixtures slice 4/5 ship; we don't need a seeded user
or DB session because the stubs raise before any persistence touch.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from iguanatrader.api.app import create_app


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


async def test_get_brief_returns_501_problem(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/research/briefs/AAPL")

    assert resp.status_code == 501
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:research-stub"
    assert body["status"] == 501
    assert "research-brief-synthesis" in body["detail"]


async def test_get_audit_trail_returns_501_problem(client: AsyncClient) -> None:
    brief_id = uuid4()
    resp = await client.get(f"/api/v1/research/briefs/{brief_id}/audit-trail")

    assert resp.status_code == 501
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:research-stub"


async def test_get_facts_returns_501_problem(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/research/facts/AAPL")

    assert resp.status_code == 501
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:research-stub"


async def test_post_refresh_returns_501_problem(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/research/briefs/AAPL/refresh", json={})

    assert resp.status_code == 501
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:research-stub"


async def test_openapi_exposes_research_dto_components(client: AsyncClient) -> None:
    """OpenAPI schema lists the research DTO components.

    Names are namespaced by the Pydantic class name; FastAPI generates
    ``BriefResponse`` / ``FactResponse`` / ``CitationDetail`` /
    ``AuditTrailEntry`` under ``components.schemas`` because each class
    inherits :class:`BaseModel`.
    """
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200

    schema = resp.json()
    components = schema.get("components", {}).get("schemas", {})
    assert "BriefResponse" in components
    assert "FactResponse" in components
    assert "CitationDetail" in components
    assert "AuditTrailEntry" in components


async def test_openapi_lists_research_paths(client: AsyncClient) -> None:
    """The four research endpoints are present under ``paths`` with the right tags."""
    resp = await client.get("/openapi.json")
    schema = resp.json()
    paths = schema.get("paths", {})

    assert "/api/v1/research/briefs/{symbol}" in paths
    assert "/api/v1/research/briefs/{brief_id}/audit-trail" in paths
    assert "/api/v1/research/facts/{symbol}" in paths
    assert "/api/v1/research/briefs/{symbol}/refresh" in paths

    # Tags propagate from the router declaration.
    brief_op = paths["/api/v1/research/briefs/{symbol}"]["get"]
    assert "research" in brief_op.get("tags", [])
