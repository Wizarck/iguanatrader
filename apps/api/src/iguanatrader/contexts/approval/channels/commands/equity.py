"""``/equity`` — read-only latest `equity_snapshots`."""

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
        latest_equity_snapshot = getattr(trading_repo, "latest_equity_snapshot", None)
        if latest_equity_snapshot is None:
            return CommandResult(
                status="ok",
                message="Equity snapshots unavailable.",
            )
        snap = await latest_equity_snapshot()
        return CommandResult(status="ok", message=f"Equity: {snap}")
    except ModuleNotFoundError:
        return CommandResult(
            status="ok",
            message="Trading context not yet installed.",
        )


SPEC: CommandSpec = CommandSpec(
    name="/equity",
    handler=_handle,
    required_role="user",
    idempotency_key_source="none",
    description_md="Latest equity snapshot.",
)
