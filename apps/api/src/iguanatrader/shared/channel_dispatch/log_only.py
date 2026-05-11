"""LogOnlyMessageDispatcher — in-tree fake (no real send).

Useful as a default when production credentials are not yet wired, and as
a deterministic test double in unit suites.
"""

from __future__ import annotations

from collections.abc import Sequence

import structlog

from iguanatrader.shared.channel_dispatch.types import (
    DispatchResult,
    OutboundMessage,
    Recipient,
)

log = structlog.get_logger("iguanatrader.shared.channel_dispatch.log_only")


class LogOnlyMessageDispatcher:
    """Logs the would-have-sent envelope; returns ``status='skipped'`` per recipient."""

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        results: list[DispatchResult] = []
        for r in recipients:
            log.info(
                "channel_dispatch.log_only.would_send",
                channel=r.channel,
                address=r.address,
                correlation_id=message.correlation_id,
                body_length=len(message.body),
            )
            results.append(
                DispatchResult(
                    channel=r.channel,
                    address=r.address,
                    status="skipped",
                    wire_message_id=None,
                    error=None,
                )
            )
        return results


__all__ = ["LogOnlyMessageDispatcher"]
