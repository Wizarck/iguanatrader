"""``/resume`` — admin command; routes into K1's risk service."""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    try:
        risk_service = importlib.import_module(
            "iguanatrader.contexts.risk.service"
        )
        record_resume = getattr(risk_service, "record_resume", None)
        if record_resume is None:
            return CommandResult(
                status="error",
                message="risk service does not expose record_resume; check slice K1 install.",
            )
        await record_resume(
            triggered_by_user_id=ctx.incoming.user_db_id,
            triggered_by_sender_id=ctx.incoming.sender_db_id,
            triggered_via_channel=ctx.incoming.channel,
        )
    except ModuleNotFoundError:
        return CommandResult(
            status="error",
            message="risk context not yet available (slice K1 must merge before P1).",
        )
    return CommandResult(status="ok", message="Trading resumed.")


SPEC: CommandSpec = CommandSpec(
    name="/resume",
    handler=_handle,
    required_role="admin",
    idempotency_key_source="payload",
    description_md="Resume trading after a halt. Admin only.",
)
