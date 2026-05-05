"""``/strategies`` — read-only active `strategy_configs` per tenant."""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    try:
        trading_repo = importlib.import_module(
            "iguanatrader.contexts.trading.repository"
        )
        list_active_strategies = getattr(trading_repo, "list_active_strategies", None)
        if list_active_strategies is None:
            return CommandResult(
                status="ok",
                message="Strategies unavailable.",
            )
        rows = await list_active_strategies()
        return CommandResult(
            status="ok",
            message=f"{len(rows)} active strategies.",
        )
    except ModuleNotFoundError:
        return CommandResult(
            status="ok",
            message="Trading context not yet installed.",
        )


SPEC: CommandSpec = CommandSpec(
    name="/strategies",
    handler=_handle,
    required_role="user",
    idempotency_key_source="none",
    description_md="List active strategy configs.",
)
