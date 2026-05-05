"""Proposals route stubs — 501 Problem until slice T4 lands the bodies.

Per design D6. Endpoints cover FR11 (list / fetch trade proposals with
their structured reasoning).
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends

from iguanatrader.api.deps import get_current_user
from iguanatrader.api.dtos.proposals import ProposalListOut, ProposalOut
from iguanatrader.persistence import User
from iguanatrader.shared.errors import NotImplementedFeatureError

log = structlog.get_logger("iguanatrader.api.routes.proposals")

router = APIRouter(prefix="/proposals", tags=["proposals"])


def _stub(method: str, path: str) -> NotImplementedFeatureError:
    """Build the canonical 501 raise for a trading-route stub."""
    log.info(
        "trading.routes.stub_invoked",
        method=method,
        path=path,
    )
    return NotImplementedFeatureError(
        detail=(f"{method} /api/v1{path} will be wired in slice T4 (trading-routes-and-daemon)."),
    )


@router.get("", response_model=ProposalListOut)
async def list_proposals(
    user: User = Depends(get_current_user),
) -> ProposalListOut:
    """List proposals for the authenticated tenant (FR11)."""
    raise _stub("GET", "/proposals")


@router.get("/{proposal_id}", response_model=ProposalOut)
async def get_proposal(
    proposal_id: UUID,
    user: User = Depends(get_current_user),
) -> ProposalOut:
    """Fetch a single proposal by id (FR11)."""
    raise _stub("GET", f"/proposals/{proposal_id}")


__all__ = ["router"]
