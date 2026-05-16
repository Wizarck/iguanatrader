"""Integration smoke for research route OpenAPI schema (slice R1 legacy).

History: slice R1 introduced these endpoints as 501 stubs (test class
named `_route_stubs.py`). Slice R5 (research-brief-synthesis) shipped
real handlers — the 501 path now only fires when no brief exists in
the DB, which requires a full auth + tenant + DB setup that's
orthogonal to the schema check this file was meant to provide.

What survives here: the two OpenAPI schema assertions that verify the
research components + paths are exposed for the W1 typegen pipeline.
The four "returns 501" tests were removed when R5 made them obsolete;
real research route integration coverage lives in the BriefService
unit tests under `tests/unit/contexts/research/`.

Filename kept for git-history continuity; spec scenarios under
"Research route stubs render 501 RFC 7807 until R5 ships" are now
documented as resolved in the R5 retro.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

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
