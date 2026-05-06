"""``/logout`` — invalidates the dashboard JWT; no-op on Telegram/WhatsApp.

Per design D2: channel auth on Telegram/WhatsApp is the
``authorized_senders`` whitelist (not session-based), so /logout is
ack-only there. On the dashboard channel, the route layer clears the
session cookie out-of-band; the dispatcher only acks.
"""

from __future__ import annotations

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    if ctx.incoming.channel == "dashboard":
        return CommandResult(
            status="ok",
            message="Session ended. Cookie clearing handled by route layer.",
        )
    return CommandResult(
        status="ok",
        message="Logout acknowledged (channel auth is whitelist-based).",
    )


SPEC: CommandSpec = CommandSpec(
    name="/logout",
    handler=_handle,
    required_role="user",
    idempotency_key_source="none",
    description_md="End the session. No-op on bot channels.",
)
