"""``/positions`` — read-only `trades WHERE state='open'`."""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    try:
        trading_repo = importlib.import_module("iguanatrader.contexts.trading.repository")
        list_open_trades = getattr(trading_repo, "list_open_trades", None)
        if list_open_trades is None:
            return CommandResult(
                status="ok",
                message="No trades context — open positions unavailable.",
            )
        rows = await list_open_trades()
        return CommandResult(
            status="ok",
            message=f"{len(rows)} open positions.",
            extra={"count": len(rows)},
        )
    except ModuleNotFoundError:
        return CommandResult(
            status="ok",
            message="Trading context not yet installed.",
        )


SPEC: CommandSpec = CommandSpec(
    name="/positions",
    handler=_handle,
    required_role="user",
    idempotency_key_source="none",
    description_md="List currently open positions.",
)
