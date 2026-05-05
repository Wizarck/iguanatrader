"""``/cost`` — read-only fold of `api_cost_events` for the current month."""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    try:
        obs_repo = importlib.import_module(
            "iguanatrader.contexts.observability.repository"
        )
        current_month_cost = getattr(obs_repo, "current_month_cost", None)
        if current_month_cost is None:
            return CommandResult(
                status="ok",
                message="Cost meter unavailable.",
            )
        usd = await current_month_cost()
        return CommandResult(status="ok", message=f"Cost MTD: ${usd:.2f}")
    except ModuleNotFoundError:
        return CommandResult(
            status="ok",
            message="Observability context not yet installed.",
        )


SPEC: CommandSpec = CommandSpec(
    name="/cost",
    handler=_handle,
    required_role="user",
    idempotency_key_source="none",
    description_md="Month-to-date API cost.",
)
