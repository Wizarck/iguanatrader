"""``/risk`` — read-only fold of `risk_evaluations` + caps."""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    try:
        risk_repo = importlib.import_module("iguanatrader.contexts.risk.repository")
        snapshot = getattr(risk_repo, "snapshot", None)
        if snapshot is None:
            return CommandResult(
                status="ok",
                message="Risk snapshot unavailable.",
            )
        snap = await snapshot()
        return CommandResult(status="ok", message=f"Risk: {snap}")
    except ModuleNotFoundError:
        return CommandResult(
            status="ok",
            message="Risk context not yet installed.",
        )


SPEC: CommandSpec = CommandSpec(
    name="/risk",
    handler=_handle,
    required_role="user",
    idempotency_key_source="none",
    description_md="Risk evaluations + caps snapshot.",
)
