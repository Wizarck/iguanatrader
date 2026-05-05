"""Dashboard channel adapter — :class:`DashboardChannel`.

Per slice P1 design open-question resolution: the dashboard route
(``POST /api/v1/approvals/{id}/approve|reject``) flows through
:func:`command_handler.dispatch` for uniformity. This adapter is the
"third Port" that consumes a dispatcher invocation; ``deliver_request``
is a no-op (the dashboard pulls via SSE) and ``start_listening`` is a
no-op (the dashboard sends via REST routes that call ``dispatch``
directly).

The heartbeat overrides return ``True`` immediately — the dashboard is
always "connected" within the FastAPI process. Inheriting
:class:`HeartbeatMixin` keeps the contract uniform across all three
channels (FR37).
"""

from __future__ import annotations

from typing import Any

import structlog

from iguanatrader.contexts.approval.channels.base import ChannelPort
from iguanatrader.contexts.approval.channels.types import ApprovalRequestRow

log = structlog.get_logger("iguanatrader.contexts.approval.channels.dashboard")


class DashboardChannel(ChannelPort):
    """In-process dashboard channel — REST + SSE plumbing."""

    def __init__(self) -> None:
        super().__init__()
        self.mark_connected()

    async def deliver_request(
        self,
        request: ApprovalRequestRow,
        recipient: Any,
    ) -> None:
        """No-op: dashboard pulls via SSE; nothing to push out-of-band."""
        log.debug(
            "approval.channel.dashboard.deliver_noop",
            request_id=str(request.id),
        )

    async def start_listening(self) -> None:
        """No-op: dashboard sends via REST routes that call dispatch directly."""

    async def stop(self) -> None:
        await self.mark_disconnected()

    async def _send_heartbeat(self) -> None:
        # In-process; nothing to probe. Always healthy.
        return None

    async def _on_disconnect(self) -> None:
        log.warning("approval.channel.dashboard.disconnected")


__all__ = ["DashboardChannel"]
