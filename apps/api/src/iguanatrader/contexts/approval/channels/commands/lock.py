"""``/lock`` — admin command; sets `tenants.feature_flags.approvals_paused=true`."""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    # #31: persist the pause for real. A failure here MUST surface as
    # ``status="error"`` — the previous code swallowed every failure as
    # ``status="ok"``, so an operator was told "Approvals paused" while the
    # flag was never written and the system kept approving + executing.
    try:
        tenant_admin = importlib.import_module("iguanatrader.contexts.observability.tenant_admin")
        await tenant_admin.set_feature_flag(
            "approvals_paused",
            True,
            tenant_id=ctx.incoming.tenant_id,
        )
    except Exception as exc:  # noqa: BLE001 — report, never silently succeed.
        return CommandResult(
            status="error",
            message=f"Failed to pause approvals: {exc}",
        )
    return CommandResult(
        status="ok",
        message="Approvals paused; existing requests resolve in-place.",
    )


SPEC: CommandSpec = CommandSpec(
    name="/lock",
    handler=_handle,
    required_role="admin",
    idempotency_key_source="payload",
    description_md="Pause new approvals. Admin only.",
)
