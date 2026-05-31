"""``/approve`` — record granted decision for the active request.

Per spec ``approval`` Requirement 5: idempotent via the DB UNIQUE on
``approval_decisions.request_id``. The handler delegates to
:meth:`ApprovalService.record_decision` which catches
:class:`IntegrityError` → :class:`ApprovalAlreadyDecidedError`.
"""

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
            message="/approve requires a request_id (Telegram callback / dashboard route).",
        )
    decided_via_channel = incoming.channel
    try:
        decision = await ctx.service.record_decision(
            request_id=incoming.request_id,
            outcome="granted",
            decided_via_channel=decided_via_channel,
            decided_by_user_id=incoming.user_db_id,
            decided_by_sender_id=incoming.sender_db_id,
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
        message=f"Approved at {decision.created_at.isoformat()}.",
        extra={"decision_id": str(decision.id)},
    )


SPEC: CommandSpec = CommandSpec(
    name="/approve",
    handler=_handle,
    required_role="user",
    idempotency_key_source="request_id",
    description_md="Approve the active proposal. Idempotent via DB UNIQUE.",
    # #31: /approve actuates a trade — denied while approvals are paused.
    blocked_when_paused=True,
)
