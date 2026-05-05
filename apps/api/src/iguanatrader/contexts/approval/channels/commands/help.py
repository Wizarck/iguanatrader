"""``/help`` — render the registry's `description_md` for all 17 commands.

Reads :data:`COMMANDS` directly. Late-import to avoid a circular dep
(commands package imports types; help imports commands).
"""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    registry = importlib.import_module("iguanatrader.contexts.approval.channels.commands")
    commands_map = registry.COMMANDS
    lines: list[str] = []
    # Sort alphabetically for stable output across channels (FR37).
    for name in sorted(commands_map.keys()):
        spec = commands_map[name]
        lines.append(f"{name} — {spec.description_md}")
    return CommandResult(status="ok", message="\n".join(lines))


SPEC: CommandSpec = CommandSpec(
    name="/help",
    handler=_handle,
    required_role="user",
    idempotency_key_source="none",
    description_md="List all 17 commands.",
)
