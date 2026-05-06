"""``/halt`` — admin command; routes into K1's risk service.

Per design D2 + cross-slice coordination: this handler imports K1's
``iguanatrader.contexts.risk.service`` lazily via :func:`importlib`
so this slice's import surface does not depend on K1 having landed.
At runtime, K1's service must be importable (merge order K1 → P1).
"""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)


async def _handle(ctx: CommandContext) -> CommandResult:
    reason = ctx.incoming.raw_args.strip() or None
    try:
        risk_service = importlib.import_module("iguanatrader.contexts.risk.service")
        record_halt = getattr(risk_service, "record_halt", None)
        if record_halt is None:
            return CommandResult(
                status="error",
                message="risk service does not expose record_halt; check slice K1 install.",
            )
        await record_halt(
            triggered_by_user_id=ctx.incoming.user_db_id,
            triggered_by_sender_id=ctx.incoming.sender_db_id,
            triggered_via_channel=ctx.incoming.channel,
            reason=reason,
        )
    except ModuleNotFoundError:
        return CommandResult(
            status="error",
            message="risk context not yet available (slice K1 must merge before P1).",
        )
    return CommandResult(
        status="ok",
        message="Trading halted.",
    )


SPEC: CommandSpec = CommandSpec(
    name="/halt",
    handler=_handle,
    required_role="admin",
    idempotency_key_source="payload",
    description_md="Halt all trading immediately. Admin only.",
)
