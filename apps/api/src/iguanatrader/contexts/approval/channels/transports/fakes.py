"""In-memory fakes for :class:`ChannelTransportPort`.

Per slice P1 design D8 + task 4.2: drives integration tests entirely
in-process. No network, no third-party SDK, no test credentials.

Test-only hooks:

* :meth:`inject_inbound` — push an :class:`IncomingCommand` so the next
  :meth:`fetch_updates` will return it.
* :meth:`pop_outbound` — drain everything :meth:`send_message` has
  enqueued so far (FIFO).
* :meth:`simulate_health_failure` — make the next ``N`` calls to
  :meth:`health_check` raise so resilience tests can drive the
  :class:`HeartbeatMixin` reconnect_loop deterministically.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from uuid import uuid4

from iguanatrader.contexts.approval.channels.types import IncomingCommand


@dataclass
class _OutboundMessage:
    recipient: str
    content: str
    message_id: str


class _FakeTransportBase:
    """Common in-memory state for the two fakes."""

    def __init__(self) -> None:
        self._outbound: list[_OutboundMessage] = []
        self._inbound: deque[IncomingCommand] = deque()
        self._health_failures_remaining: int = 0
        self._health_check_calls: int = 0

    async def send_message(self, recipient: str, content: str) -> str:
        message_id = uuid4().hex
        self._outbound.append(
            _OutboundMessage(
                recipient=recipient,
                content=content,
                message_id=message_id,
            )
        )
        return message_id

    async def fetch_updates(self) -> list[IncomingCommand]:
        out: list[IncomingCommand] = []
        while self._inbound:
            out.append(self._inbound.popleft())
        return out

    async def health_check(self) -> bool:
        self._health_check_calls += 1
        if self._health_failures_remaining > 0:
            self._health_failures_remaining -= 1
            raise RuntimeError("simulated wire failure")
        return True

    # Test-only hooks ---------------------------------------------------

    def inject_inbound(self, incoming: IncomingCommand) -> None:
        self._inbound.append(incoming)

    def pop_outbound(self) -> list[_OutboundMessage]:
        out = list(self._outbound)
        self._outbound.clear()
        return out

    def simulate_health_failure(self, times: int) -> None:
        self._health_failures_remaining = times

    @property
    def health_check_call_count(self) -> int:
        return self._health_check_calls


class FakeTelegramTransport(_FakeTransportBase):
    """In-memory stub for Telegram's wire surface."""


class FakeHermesTransport(_FakeTransportBase):
    """In-memory stub for the Hermes / Meta Cloud API wire surface."""


__all__ = [
    "FakeHermesTransport",
    "FakeTelegramTransport",
]
