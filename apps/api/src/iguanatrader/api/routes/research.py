"""Research routes — ``GET /briefs/{symbol}``, audit-trail, facts, refresh.

Per design D6 (slice R1): R1 lands route stubs that raise
:class:`ResearchStubNotImplementedError` (a slice-local
:class:`IguanaError` subclass — see
:mod:`iguanatrader.contexts.research.errors`). The slice-5 global
``IguanaError`` handler renders these as 501 RFC 7807 Problem Details
with ``type=urn:iguanatrader:error:research-stub``.

R5 (``research-brief-synthesis``) replaces each handler body in-place;
the route signatures + DTOs do not change. Keeping the surface stable
at R1 means the typegen pipeline produces the canonical
``shared-types/index.ts`` once, and downstream slices (W1, R2/R3/R4)
consume the typed client without churn.

The router carries no prefix (slice-5
:func:`register_routers` adds ``/api/v1`` for every dynamically-
discovered router); it does declare ``tags=["research"]`` so the
OpenAPI schema groups these endpoints.

Hard rules per AGENTS.md §4:

* All errors RFC 7807 ``application/problem+json`` — handled globally
  via :func:`IguanaError` exception handler from slice 5.
* structlog event names ``api.research.<entity>.<action>``.
* No float for money — none here yet (R5's brief response carries
  ``score_overall: Decimal``; the DTO declares the precise type).
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter

from iguanatrader.api.dtos.research import (
    AuditTrailEntry,
    BriefRefreshRequest,
    BriefResponse,
    FactResponse,
)
from iguanatrader.contexts.research.errors import ResearchStubNotImplementedError

log = structlog.get_logger("iguanatrader.api.routes.research")

router = APIRouter(prefix="/research", tags=["research"])


def _stub_detail(endpoint: str) -> str:
    """Detail string fed into the 501 Problem body.

    Centralised so R5 can grep + replace one helper rather than four
    inline string literals when filling in real handlers.
    """
    return f"{endpoint} ships in slice R5 (research-brief-synthesis)"


@router.get("/briefs/{symbol}", response_model=BriefResponse)
async def get_brief(symbol: str) -> BriefResponse:
    """Return the vigent research brief for ``symbol`` for the current tenant.

    R1 STUB — raises 501 until R5 ships brief synthesis. The slice-5
    global handler renders the response as
    ``application/problem+json`` with the canonical research-stub
    type URI.
    """
    log.info(
        "api.research.stub_called",
        endpoint="GET /research/briefs/{symbol}",
        symbol=symbol,
    )
    raise ResearchStubNotImplementedError(
        detail=_stub_detail("GET /research/briefs/{symbol}"),
    )


@router.get(
    "/briefs/{brief_id}/audit-trail",
    response_model=list[AuditTrailEntry],
)
async def get_brief_audit_trail(brief_id: UUID) -> list[AuditTrailEntry]:
    """Return the audit-trail array of an existing brief (FR70)."""
    log.info(
        "api.research.stub_called",
        endpoint="GET /research/briefs/{brief_id}/audit-trail",
        brief_id=str(brief_id),
    )
    raise ResearchStubNotImplementedError(
        detail=_stub_detail("GET /research/briefs/{brief_id}/audit-trail"),
    )


@router.get("/facts/{symbol}", response_model=list[FactResponse])
async def get_facts(symbol: str) -> list[FactResponse]:
    """Return the bitemporal facts for ``symbol`` (R5 wires PiT filtering)."""
    log.info(
        "api.research.stub_called",
        endpoint="GET /research/facts/{symbol}",
        symbol=symbol,
    )
    raise ResearchStubNotImplementedError(
        detail=_stub_detail("GET /research/facts/{symbol}"),
    )


@router.post("/briefs/{symbol}/refresh", response_model=BriefResponse)
async def refresh_brief(
    symbol: str,
    body: BriefRefreshRequest,
) -> BriefResponse:
    """Trigger a brief refresh for ``symbol``; returns the new vigent brief."""
    log.info(
        "api.research.stub_called",
        endpoint="POST /research/briefs/{symbol}/refresh",
        symbol=symbol,
    )
    raise ResearchStubNotImplementedError(
        detail=_stub_detail("POST /research/briefs/{symbol}/refresh"),
    )


__all__ = [
    "router",
]
