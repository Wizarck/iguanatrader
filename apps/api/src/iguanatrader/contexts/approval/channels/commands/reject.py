"""``/reject`` — record rejected decision (optionally with reason text)."""

from __future__ import annotations

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)
from iguanatrader.contexts.approval.errors import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    incoming = ctx.incoming
    if incoming.request_id is None:
        return CommandResult(
            status="error",
            message="/reject requires a request_id.",
        )
    reason = incoming.raw_args.strip() or None
    try:
        decision = await ctx.service.record_decision(
            request_id=incoming.request_id,
            outcome="rejected",
            decided_via_channel=incoming.channel,
            decided_by_user_id=incoming.user_db_id,
            decided_by_sender_id=incoming.sender_db_id,
            reason=reason,
        )
    except ApprovalAlreadyDecidedError as exc:
        return CommandResult(
            status="ok",
            message=str(exc.detail or exc.title),
            extra={"already_decided": True},
        )
    except ApprovalNotFoundError as exc:
        return CommandResult(
            status="error",
            message=str(exc.detail or exc.title),
        )
    return CommandResult(
        status="ok",
        message=f"Rejected at {decision.created_at.isoformat()}.",
        extra={"decision_id": str(decision.id), "reason": reason},
    )


SPEC: CommandSpec = CommandSpec(
    name="/reject",
    handler=_handle,
    required_role="user",
    idempotency_key_source="request_id",
    description_md="Reject the active proposal. Optional reason text.",
)
