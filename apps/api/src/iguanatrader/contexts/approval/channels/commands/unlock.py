"""``/unlock`` — admin command; clears `approvals_paused` feature flag."""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    # #31: clear the pause for real; report failures instead of a
    # misleading "ok" (see lock.py for the rationale).
    try:
        tenant_admin = importlib.import_module("iguanatrader.contexts.observability.tenant_admin")
        await tenant_admin.set_feature_flag(
            "approvals_paused",
            False,
            tenant_id=ctx.incoming.tenant_id,
        )
    except Exception as exc:  # noqa: BLE001 — report, never silently succeed.
        return CommandResult(
            status="error",
            message=f"Failed to resume approvals: {exc}",
        )
    return CommandResult(status="ok", message="Approvals resumed.")


SPEC: CommandSpec = CommandSpec(
    name="/unlock",
    handler=_handle,
    required_role="admin",
    idempotency_key_source="payload",
    description_md="Resume approvals after /lock. Admin only.",
)
