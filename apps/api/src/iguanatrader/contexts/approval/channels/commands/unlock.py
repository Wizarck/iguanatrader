"""``/unlock`` — admin command; clears `approvals_paused` feature flag."""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    try:
        tenant_admin = importlib.import_module(
            "iguanatrader.contexts.observability.tenant_admin"
        )
        set_flag = getattr(tenant_admin, "set_feature_flag", None)
        if set_flag is None:
            return CommandResult(
                status="ok",
                message="Feature-flag admin unavailable.",
            )
        await set_flag("approvals_paused", False)
    except ModuleNotFoundError:
        return CommandResult(
            status="ok",
            message="Observability context not yet installed; unlock is a no-op.",
        )
    return CommandResult(status="ok", message="Approvals resumed.")


SPEC: CommandSpec = CommandSpec(
    name="/unlock",
    handler=_handle,
    required_role="admin",
    idempotency_key_source="payload",
    description_md="Resume approvals after /lock. Admin only.",
)
