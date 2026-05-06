"""ChannelTransportPort — abstract wire-format facade (Protocol).

Per slice P1 design D8: every channel adapter consumes a transport
behind this Port. Telegram + Hermes/WhatsApp share the same shape;
real wire clients land later behind the same Protocol so swapping is
zero-cost on the consumer side.

Protocol shape (smallest possible surface):

* :meth:`send_message` — fire one outbound message; return the wire
  message id for audit.
* :meth:`fetch_updates` — drain pending inbound messages (long-poll
  for Telegram; webhook-buffer for Meta Cloud API). Return zero or
  more :class:`IncomingCommand` instances normalised to the canonical
  shape.
* :meth:`health_check` — single-shot probe used by
  :class:`HeartbeatMixin._send_heartbeat`. Returns ``True`` on
  success, raises any exception on failure (the heartbeat loop catches
  + sleeps + retries per the canonical backoff).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from iguanatrader.contexts.approval.channels.types import IncomingCommand


@runtime_checkable
class ChannelTransportPort(Protocol):
    """Wire-format facade — Telegram, WhatsApp, or any future channel."""

    async def send_message(self, recipient: str, content: str) -> str:
        """Send one outbound message. Returns the wire message id."""
        ...

    async def fetch_updates(self) -> list[IncomingCommand]:
        """Drain pending inbound updates (long-poll for Telegram; webhook for Meta)."""
        ...

    async def health_check(self) -> bool:
        """Probe the wire. Return ``True`` on success; raise on failure."""
        ...


__all__ = ["ChannelTransportPort"]
