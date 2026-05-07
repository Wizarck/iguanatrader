"""Proposals routes — slice T4 fills the read body + adds manual-approve.

Endpoints:

* ``GET /proposals/{proposal_id}`` (T4 body fill) — returns the
  :class:`ProposalOut` projection.
* ``POST /proposals/{proposal_id}/approve`` (T4 NEW) — operator-override
  approve path. Bypasses P1's channel flow; publishes
  :class:`ProposalApproved` directly. slowapi-limited to 5/min per
  the slice-T4 §4.5 rate-limit budget.

Other stubs (``list_proposals``) remain 501 until a follow-up slice
fills them — the keystone path is single-proposal lookup + approve.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.proposals import ProposalListOut, ProposalOut
from iguanatrader.api.limiting import limiter
from iguanatrader.contexts.trading.events import ProposalApproved
from iguanatrader.contexts.trading.repository import TradeProposalRepository
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var
from iguanatrader.shared.errors import (
    NotFoundError,
    NotImplementedFeatureError,
)

log = structlog.get_logger("iguanatrader.api.routes.proposals")

router = APIRouter(prefix="/proposals", tags=["proposals"])


def _stub(method: str, path: str) -> NotImplementedFeatureError:
    """Build the canonical 501 raise for a trading-route stub."""
    log.info("trading.routes.stub_invoked", method=method, path=path)
    return NotImplementedFeatureError(
        detail=(
            f"{method} /api/v1{path} will be wired in a follow-up slice (T4 ships "
            "single-proposal lookup + manual-approve only)."
        ),
    )


@router.get("", response_model=ProposalListOut)
async def list_proposals(
    user: User = Depends(get_current_user),
) -> ProposalListOut:
    """List proposals for the authenticated tenant — list-stub remains 501."""
    raise _stub("GET", "/proposals")


@router.get("/{proposal_id}", response_model=ProposalOut)
async def get_proposal(
    proposal_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalOut:
    """Fetch a single proposal by id (FR11; slice T4 §4.3)."""
    log.info("api.proposals.get", proposal_id=str(proposal_id))
    session_var.set(db)
    repo = TradeProposalRepository()
    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise NotFoundError(detail=f"Proposal {proposal_id} not found.")
    return ProposalOut.model_validate(proposal)


@router.post("/{proposal_id}/approve", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def manual_approve(
    request: Request,
    proposal_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Operator-override approve path (slice T4 §4.5).

    Bypasses the P1 channel flow + emits :class:`ProposalApproved` directly
    on the in-process bus. The :class:`TradingService.execute_on_approval_handler`
    re-checks idempotency via :class:`OrderRepository.get_by_proposal_id`,
    so a redundant manual approve is a no-op.

    Rate-limited 5/min per (ip, user) compound key.
    """
    log.info(
        "api.proposals.manual_approve",
        proposal_id=str(proposal_id),
        user_id=str(user.id),
    )
    session_var.set(db)

    repo = TradeProposalRepository()
    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise NotFoundError(detail=f"Proposal {proposal_id} not found.")

    from iguanatrader.contexts.approval.bootstrap import get_message_bus

    bus = get_message_bus()
    await bus.publish(
        ProposalApproved(
            tenant_id=proposal.tenant_id,
            proposal_id=proposal_id,
            approved_by_user_id=user.id,
        )
    )
    log.info(
        "api.proposals.manual_approve.published",
        proposal_id=str(proposal_id),
        approved_by=str(user.id),
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "proposal_id": str(proposal_id),
            "approved_by_user_id": str(user.id),
            "status": "queued",
        },
    )


__all__ = ["router"]
