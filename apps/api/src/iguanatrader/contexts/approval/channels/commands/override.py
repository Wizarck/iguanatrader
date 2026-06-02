"""``/override`` — admin command; routes into K1's risk service.

Per design D2 + spec footnote: requires a reason of >= 20 chars; the
chained double-confirmation prompt is owned by the channel adapter
(not the dispatcher) — the audit row lives in K1's ``risk_overrides``
table.
"""

from __future__ import annotations

import importlib

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
)

_REASON_MIN_LEN: int = 20


async def _handle(ctx: CommandContext) -> CommandResult:
    reason = ctx.incoming.raw_args.strip()
    if len(reason) < _REASON_MIN_LEN:
        return CommandResult(
            status="error",
            message=(f"/override requires a reason of at least {_REASON_MIN_LEN} chars."),
        )
    try:
        risk_service = importlib.import_module("iguanatrader.contexts.risk.service")
        record_override = getattr(risk_service, "record_override", None)
        if record_override is None:
            return CommandResult(
                status="error",
                message="risk service does not expose record_override; check slice K1 install.",
            )
        await record_override(
            proposal_id=ctx.incoming.request_id,
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
    return CommandResult(status="ok", message="Override recorded.")


SPEC: CommandSpec = CommandSpec(
    name="/override",
    handler=_handle,
    required_role="admin",
    idempotency_key_source="payload",
    description_md=("Override a risk decision. Reason >= 20 chars. Admin only."),
    # #31: /override forces a risk-blocked proposal through — denied while
    # approvals are paused.
    blocked_when_paused=True,
)
