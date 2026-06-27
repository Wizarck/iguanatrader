"""Approval routes — list pending + approve + reject (dashboard channel).

Auto-discovered by slice 5's
:func:`iguanatrader.api.routes.register_routers` — exports a top-level
``router: APIRouter``. No edit to ``app.py`` or ``routes/__init__.py``.

Endpoints:

* ``GET /api/v1/approvals`` — list pending requests for the caller's
  tenant.
* ``POST /api/v1/approvals/{id}/approve`` — record granted decision
  via the dashboard channel; flows through
  :func:`command_handler.dispatch` for uniformity (FR37 invariant).
* ``POST /api/v1/approvals/{id}/reject`` — record rejected decision
  with optional reason.

Errors raise :class:`IguanaError` subclasses (slice-local
:class:`ApprovalNotFoundError` / :class:`ApprovalAlreadyDecidedError`);
the slice-5 global handler renders RFC 7807 automatically.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.approvals import (
    ApprovalCommandResult,
    RejectionRequest,
)
from iguanatrader.api.dtos.approvals import (
    ApprovalRequest as ApprovalRequestDto,
)
from iguanatrader.contexts.approval.bootstrap import (
    get_message_bus,
    make_repository,
    make_service,
)
from iguanatrader.contexts.approval.channels.command_handler import dispatch
from iguanatrader.contexts.approval.channels.types import IncomingCommand
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var

log = structlog.get_logger("iguanatrader.api.routes.approvals")

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalRequestDto])
async def list_pending(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalRequestDto]:
    """Return all pending approval requests for the caller's tenant."""
    session_var.set(db)
    repo = make_repository()
    rows = await repo.list_pending()
    return [
        ApprovalRequestDto(
            id=r.id,
            tenant_id=r.tenant_id,
            proposal_id=r.proposal_id,
            delivered_to_channels=r.delivered_to_channels,
            timeout_seconds=r.timeout_seconds,
            expires_at=r.expires_at,
            created_at=r.created_at,
            delivery_failures=r.delivery_failures,
            action_type=getattr(r, "action_type", "entry"),
            trade_id=getattr(r, "trade_id", None),
        )
        for r in rows
    ]


@router.post("/{request_id}/approve", response_model=ApprovalCommandResult)
async def approve(
    request_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApprovalCommandResult:
    """Record a granted decision via the dashboard channel."""
    session_var.set(db)
    incoming = IncomingCommand(
        command_name="/approve",
        raw_args="",
        sender_external_id=str(user.id),
        channel="dashboard",
        tenant_id=user.tenant_id,
        request_id=request_id,
        sender_db_id=None,
        user_db_id=user.id,
        role="admin" if user.role == "god_admin" else "user",
    )
    result = await dispatch(
        incoming,
        service=make_service(),
        message_bus=get_message_bus(),
        repository=make_repository(),
    )
    return ApprovalCommandResult(
        status=result.status,
        message=result.message,
        extra=dict(result.extra) if result.extra else None,
    )


@router.post("/{request_id}/reject", response_model=ApprovalCommandResult)
async def reject(
    request_id: UUID,
    body: RejectionRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApprovalCommandResult:
    """Record a rejected decision via the dashboard channel."""
    session_var.set(db)
    raw_args = body.reason if (body is not None and body.reason) else ""
    incoming = IncomingCommand(
        command_name="/reject",
        raw_args=raw_args,
        sender_external_id=str(user.id),
        channel="dashboard",
        tenant_id=user.tenant_id,
        request_id=request_id,
        sender_db_id=None,
        user_db_id=user.id,
        role="admin" if user.role == "god_admin" else "user",
    )
    result = await dispatch(
        incoming,
        service=make_service(),
        message_bus=get_message_bus(),
        repository=make_repository(),
    )
    return ApprovalCommandResult(
        status=result.status,
        message=result.message,
        extra=dict(result.extra) if result.extra else None,
    )


__all__ = ["router"]
