"""``/budget`` — admin command; reads + sets per-tenant monthly cap.

Per design D2: the budget table is owned by slice O1; this command
routes via lazy import.
"""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    try:
        obs_repo = importlib.import_module("iguanatrader.contexts.observability.repository")
    except ModuleNotFoundError:
        return CommandResult(
            status="ok",
            message="Observability context not yet installed.",
        )
    raw = ctx.incoming.raw_args.strip()
    if not raw:
        get_budget = getattr(obs_repo, "get_monthly_budget", None)
        if get_budget is None:
            return CommandResult(
                status="ok",
                message="Budget unavailable.",
            )
        cap = await get_budget()
        return CommandResult(status="ok", message=f"Monthly budget: ${cap:.2f}")
    try:
        new_cap = float(raw)
    except ValueError:
        return CommandResult(
            status="error",
            message=f"Invalid budget: {raw!r}; expected USD amount.",
        )
    set_budget = getattr(obs_repo, "set_monthly_budget", None)
    if set_budget is None:
        return CommandResult(
            status="ok",
            message="Budget setter unavailable.",
        )
    await set_budget(new_cap)
    return CommandResult(status="ok", message=f"Budget set to ${new_cap:.2f}.")


SPEC: CommandSpec = CommandSpec(
    name="/budget",
    handler=_handle,
    required_role="admin",
    idempotency_key_source="payload",
    description_md="Read or set the monthly API cost cap. Admin only.",
)
