"""ChannelPort — abstract base for every approval-channel adapter.

Per slice P1 design D1 + slice 2 :class:`HeartbeatMixin`: every channel
inherits the connection-state machine + canonical
:func:`backoff_seconds` reconnect ladder. Subclasses override only:

* :meth:`_send_heartbeat` — transport-specific probe (delegated to
  :meth:`ChannelTransportPort.health_check`).
* :meth:`_on_disconnect` — transport-specific cleanup + alert
  emission. MUST NOT raise (per :class:`HeartbeatMixin` contract).

Three abstract methods carry the channel-level contract:

* :meth:`deliver_request` — fan-out target invoked by the service
  when a new :class:`ApprovalRequest` is created.
* :meth:`start_listening` — begin processing inbound updates; calls
  :func:`command_handler.dispatch` after sender verification +
  payload normalisation.
* :meth:`stop` — gracefully shut down (cancel listener task, etc.).

Hard rule per design D3: subclasses MUST NOT use ``time.sleep`` or
``asyncio.sleep`` with hardcoded numeric literals. Reconnect timing is
inherited from :class:`HeartbeatMixin` which delegates to
:func:`iguanatrader.shared.backoff.backoff_seconds`. Deviation requires
an ADR (NFR-R7).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from iguanatrader.contexts.approval.channels.types import ApprovalRequestRow
from iguanatrader.shared.heartbeat import HeartbeatMixin


class ChannelPort(HeartbeatMixin):
    """Abstract approval-channel adapter."""

    @abstractmethod
    async def deliver_request(
        self,
        request: ApprovalRequestRow,
        recipient: Any,
    ) -> None:
        """Render and send the approval question to ``recipient``."""
        raise NotImplementedError

    @abstractmethod
    async def start_listening(self) -> None:
        """Begin processing inbound updates from this channel."""
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully tear down the listener + close transport."""
        raise NotImplementedError


__all__ = ["ChannelPort"]
