"""``/status`` — read-only fold of trading + risk + approval state.

The handler builds a tenant-scoped status snapshot. Cross-context reads
are best-effort: when the trading or risk context is not yet present
(parallel-slice landing window), the relevant subsection reports
"unavailable" rather than failing the whole command.
"""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    sections: list[str] = []
    # Approval section — always available.
    if ctx.repository is not None:
        try:
            pending = await ctx.repository.list_pending()
            sections.append(f"approval: {len(pending)} pending")
        except Exception:
            sections.append("approval: unavailable")
    # Trading section — optional cross-context.
    try:
        importlib.import_module("iguanatrader.contexts.trading.service")
        sections.append("trading: available")
    except ModuleNotFoundError:
        sections.append("trading: not yet installed")
    # Risk section — optional cross-context.
    try:
        importlib.import_module("iguanatrader.contexts.risk.service")
        sections.append("risk: available")
    except ModuleNotFoundError:
        sections.append("risk: not yet installed")
    return CommandResult(status="ok", message="; ".join(sections))


SPEC: CommandSpec = CommandSpec(
    name="/status",
    handler=_handle,
    required_role="user",
    idempotency_key_source="none",
    description_md="Snapshot of trading + risk + approval state.",
)
