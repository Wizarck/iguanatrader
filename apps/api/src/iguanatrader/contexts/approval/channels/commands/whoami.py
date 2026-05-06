"""``/whoami`` — read-only echo of caller's identity."""

from __future__ import annotations

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    incoming = ctx.incoming
    parts = [
        f"channel={incoming.channel}",
        f"tenant_id={incoming.tenant_id}",
        f"sender={incoming.sender_external_id}",
    ]
    if incoming.user_db_id is not None:
        parts.append(f"user_id={incoming.user_db_id}")
    return CommandResult(status="ok", message="; ".join(parts))


SPEC: CommandSpec = CommandSpec(
    name="/whoami",
    handler=_handle,
    required_role="user",
    idempotency_key_source="none",
    description_md="Echo your identity (tenant + sender).",
)
