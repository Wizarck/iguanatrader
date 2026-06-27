"""MCP human-in-the-loop action tools — slice ``mcp-hitl-approvals``.

Exposes the operator's approve / reject / halt / resume / lock / unlock
actions (plus the ``list_pending_approvals`` read) on the MCP REST
surface so the external Hermes gateway (which owns the WhatsApp +
Telegram plugins) can close the hands-off approval loop.

Trust boundary (design D1 — the linchpin): every action requires the
operator's ``channel`` + ``external_id`` (supplied by Hermes, which knows
the verified WhatsApp/Telegram sender). The handler **revalidates** that
pair against the ``authorized_senders`` whitelist and resolves the
privilege ``role`` **from the database** — the MCP service bearer token
alone NEVER authorises a money action. Per Gate E ("owner siempre")
*every* action tool requires the tenant ``owner``.

No approval/kill-switch/idempotency logic is duplicated: each handler
builds an :class:`IncomingCommand` and calls the existing
:func:`command_handler.dispatch`, inheriting the audit-hardened guards
(#30 expiry, #31 pause, #39 tenant-keyed idempotency, #27 durable
kill-switch via :func:`risk.service.record_halt`).
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_db
from iguanatrader.api.routes.mcp import (
    MCPActionFailedError,
    MCPForbiddenError,
    MCPNotConfiguredError,
    _bearer_auth,
    _bind_tenant_context,
)
from iguanatrader.contexts.approval.bootstrap import (
    get_message_bus,
    make_repository,
    make_service,
)
from iguanatrader.contexts.approval.channels.command_handler import dispatch
from iguanatrader.contexts.approval.channels.types import (
    CommandResult,
    IncomingCommand,
)
from iguanatrader.shared.contextvars import session_var, tenant_id_var

log = structlog.get_logger("iguanatrader.api.routes.mcp_hitl")

router = APIRouter(prefix="/mcp/tools", tags=["mcp"])

#: Static pepper so a logged sender hash is not a bare SHA of a phone
#: number / chat id (defence against rainbow-table reversal in logs). The
#: hash only ever appears in structlog for deny events — never echoed to
#: the caller (design D1: deny without leaking the operator identity).
_LOG_PEPPER = "iguanatrader.mcp-hitl.v1"

#: Operator channels Hermes forwards. ``dashboard`` is intentionally not
#: accepted here — that path has its own JWT-authenticated routes.
OperatorChannel = Literal["telegram", "whatsapp"]


def _sender_hash(external_id: str) -> str:
    return hashlib.sha256(f"{_LOG_PEPPER}:{external_id}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Tool registry — folded into ``GET /mcp/tools`` by ``mcp_tools.list_tools``
# ---------------------------------------------------------------------------


def _action_schema(*extra_props: tuple[str, dict[str, Any]], required: list[str]) -> dict[str, Any]:
    props: dict[str, Any] = {
        "channel": {"type": "string", "enum": ["telegram", "whatsapp"]},
        "external_id": {
            "type": "string",
            "description": "Operator's verified channel id (Telegram chat id / WhatsApp phone).",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Hermes callback/interactive id — dedupes retries.",
        },
    }
    for name, schema in extra_props:
        props[name] = schema
    return {
        "type": "object",
        "properties": props,
        "required": ["channel", "external_id", *required],
    }


HITL_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "approve_proposal",
        "description": "Approve a pending proposal (owner only). Revalidates the operator identity.",
        "input_schema": _action_schema(
            ("request_id", {"type": "string", "description": "approval_requests.id"}),
            required=["request_id"],
        ),
    },
    {
        "name": "reject_proposal",
        "description": "Reject a pending proposal (owner only).",
        "input_schema": _action_schema(
            ("request_id", {"type": "string", "description": "approval_requests.id"}),
            ("reason", {"type": "string", "description": "Optional rejection reason."}),
            required=["request_id"],
        ),
    },
    {
        "name": "halt_trading",
        "description": "Activate the kill-switch (owner only). Durable — survives a restart.",
        "input_schema": _action_schema(
            ("reason", {"type": "string", "description": "Optional halt reason."}),
            required=[],
        ),
    },
    {
        "name": "resume_trading",
        "description": "Deactivate the kill-switch (owner only).",
        "input_schema": _action_schema(required=[]),
    },
    {
        "name": "lock",
        "description": "Pause new approvals (owner only).",
        "input_schema": _action_schema(required=[]),
    },
    {
        "name": "unlock",
        "description": "Resume approvals after a lock (owner only).",
        "input_schema": _action_schema(required=[]),
    },
    {
        "name": "list_pending_approvals",
        "description": "List the configured tenant's pending approval requests with proposal summary.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class _ActionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: OperatorChannel
    external_id: str
    idempotency_key: str | None = None


class ApproveProposalRequest(_ActionBase):
    request_id: UUID


class RejectProposalRequest(_ActionBase):
    request_id: UUID
    reason: str | None = None


class HaltTradingRequest(_ActionBase):
    reason: str | None = None


class ResumeTradingRequest(_ActionBase):
    pass


class LockRequest(_ActionBase):
    pass


class UnlockRequest(_ActionBase):
    pass


class ActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    message: str
    extra: dict[str, Any] | None = None


class PendingApprovalItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    # NULL for exit-approval rows (WS-5 PR-B), which carry ``trade_id``.
    proposal_id: UUID | None = None
    symbol: str | None
    side: str | None
    quantity: str | None
    entry_price_indicative: str | None
    stop_price: str | None
    expires_at: str


class ListPendingApprovalsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pending: list[PendingApprovalItem]


# ---------------------------------------------------------------------------
# Adapter — identity revalidation + owner gate + dispatch (design D1/D2/D3)
# ---------------------------------------------------------------------------


async def _resolve_and_dispatch(
    db: AsyncSession,
    *,
    command_name: str,
    channel: OperatorChannel,
    external_id: str,
    request_id: UUID | None = None,
    raw_args: str = "",
    idempotency_key: str | None = None,
) -> CommandResult:
    """Revalidate the operator, enforce the owner gate, then dispatch.

    Layer 2 of the trust model: a missing/disabled ``authorized_senders``
    row or a non-``owner`` role is denied with HTTP 403 and no proposal
    echo. The privilege role is read from the DB row, never the payload.
    """
    tenant_id = tenant_id_var.get()
    if tenant_id is None:  # _bind_tenant_context must have run
        raise MCPNotConfiguredError(detail="MCP tenant context is not bound.")
    session_var.set(db)

    repo = make_repository()
    resolved = await repo.resolve_enabled_sender(
        tenant_id=tenant_id,
        channel=channel,
        external_id=external_id,
    )
    if resolved is None:
        log.warning(
            "api.mcp.hitl.sender_denied",
            command=command_name,
            channel=channel,
            sender_hash=_sender_hash(external_id),
        )
        raise MCPForbiddenError(detail="Sender is not authorised for HITL actions.")
    if resolved.role != "owner":
        log.warning(
            "api.mcp.hitl.owner_required",
            command=command_name,
            channel=channel,
            sender_hash=_sender_hash(external_id),
            role=resolved.role,
        )
        raise MCPForbiddenError(detail="This action requires the tenant owner.")

    incoming = IncomingCommand(
        command_name=command_name,
        raw_args=raw_args,
        sender_external_id=external_id,
        channel=channel,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        request_id=request_id,
        sender_db_id=resolved.id,
        user_db_id=None,
        # owner → admin gate (resolved from DB, never the request payload).
        role="admin",
    )
    return await dispatch(
        incoming,
        service=make_service(),
        message_bus=get_message_bus(),
        repository=repo,
    )


def _to_response(result: CommandResult) -> ActionResponse:
    """Map a :class:`CommandResult` to the HTTP surface.

    ``denied`` (role/pause) → 403; ``error``/``unknown_command`` → 422;
    ``ok`` → 200 body. ``ApprovalExpiredError`` (#30) is raised inside
    dispatch and propagates to the 410 RFC 7807 handler unchanged.
    """
    if result.status == "denied":
        raise MCPForbiddenError(detail=result.message)
    if result.status in ("error", "unknown_command"):
        raise MCPActionFailedError(detail=result.message)
    return ActionResponse(
        status=result.status,
        message=result.message,
        extra=dict(result.extra) if result.extra else None,
    )


async def _run_action(db: AsyncSession, **kwargs: Any) -> ActionResponse:
    result = await _resolve_and_dispatch(db, **kwargs)
    # Explicit commit on success — the request session (``get_db``) does
    # not auto-commit, mirroring ``mcp_tools`` action routes. Durable
    # commands (halt/resume) already committed inside the handler; a
    # second commit on the clean session is a harmless no-op.
    if result.status == "ok":
        await db.commit()
    return _to_response(result)


# ---------------------------------------------------------------------------
# Action routes
# ---------------------------------------------------------------------------


@router.post(
    "/approve_proposal",
    response_model=ActionResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def approve_proposal(
    body: ApproveProposalRequest,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """Approve a pending proposal on the operator's behalf (owner only)."""
    return await _run_action(
        db,
        command_name="/approve",
        channel=body.channel,
        external_id=body.external_id,
        request_id=body.request_id,
        idempotency_key=body.idempotency_key,
    )


@router.post(
    "/reject_proposal",
    response_model=ActionResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def reject_proposal(
    body: RejectProposalRequest,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """Reject a pending proposal (owner only)."""
    return await _run_action(
        db,
        command_name="/reject",
        channel=body.channel,
        external_id=body.external_id,
        request_id=body.request_id,
        raw_args=body.reason or "",
        idempotency_key=body.idempotency_key,
    )


@router.post(
    "/halt_trading",
    response_model=ActionResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def halt_trading(
    body: HaltTradingRequest,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """Activate the kill-switch durably (owner only)."""
    return await _run_action(
        db,
        command_name="/halt",
        channel=body.channel,
        external_id=body.external_id,
        raw_args=body.reason or "",
        idempotency_key=body.idempotency_key,
    )


@router.post(
    "/resume_trading",
    response_model=ActionResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def resume_trading(
    body: ResumeTradingRequest,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """Deactivate the kill-switch (owner only)."""
    return await _run_action(
        db,
        command_name="/resume",
        channel=body.channel,
        external_id=body.external_id,
        idempotency_key=body.idempotency_key,
    )


@router.post(
    "/lock",
    response_model=ActionResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def lock(
    body: LockRequest,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """Pause new approvals (owner only)."""
    return await _run_action(
        db,
        command_name="/lock",
        channel=body.channel,
        external_id=body.external_id,
        idempotency_key=body.idempotency_key,
    )


@router.post(
    "/unlock",
    response_model=ActionResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def unlock(
    body: UnlockRequest,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """Resume approvals after a lock (owner only)."""
    return await _run_action(
        db,
        command_name="/unlock",
        channel=body.channel,
        external_id=body.external_id,
        idempotency_key=body.idempotency_key,
    )


@router.post(
    "/list_pending_approvals",
    response_model=ListPendingApprovalsResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def list_pending_approvals(
    db: AsyncSession = Depends(get_db),
) -> ListPendingApprovalsResponse:
    """List pending approval requests for the configured tenant.

    Read-only (no per-operator gate beyond bearer + tenant binding) so
    Hermes can answer "what needs my approval?". Tenant-scoped by the
    slice-3 listener; each item carries the proposal summary + expiry.
    """
    from iguanatrader.contexts.trading.models import TradeProposal

    session_var.set(db)
    repo = make_repository()
    rows = await repo.list_pending()

    items: list[PendingApprovalItem] = []
    for r in rows:
        # Exit-approval rows (WS-5 PR-B) have no proposal to enrich from.
        proposal = (
            await db.get(TradeProposal, r.proposal_id)
            if getattr(r, "proposal_id", None) is not None
            else None
        )
        items.append(
            PendingApprovalItem(
                request_id=r.id,
                proposal_id=r.proposal_id,
                symbol=getattr(proposal, "symbol", None),
                side=getattr(proposal, "side", None),
                quantity=(str(proposal.quantity) if proposal is not None else None),
                entry_price_indicative=(
                    str(proposal.entry_price_indicative)
                    if proposal is not None and proposal.entry_price_indicative is not None
                    else None
                ),
                stop_price=(
                    str(proposal.stop_price)
                    if proposal is not None and proposal.stop_price is not None
                    else None
                ),
                expires_at=r.expires_at.isoformat(),
            )
        )
    log.info("api.mcp.hitl.list_pending", count=len(items))
    return ListPendingApprovalsResponse(pending=items)


__all__ = ["HITL_TOOL_SPECS", "router"]
