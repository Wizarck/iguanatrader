"""HeartbeatMixin — connection-state machine for live adapters.

Per design decision D6 (slice 2 ``shared-primitives``): IBKR adapter,
Telegram channel, Hermes/WhatsApp channel — every adapter that holds a
long-lived live connection inherits this mixin. The state machine has
three states (``CONNECTED``, ``RECONNECTING``, ``DISCONNECTED``) and
three idempotent transition methods (``mark_connected``,
``mark_disconnected``, ``mark_reconnecting``).

Idempotency invariant: calling a transition method when the state is
already at the target is a no-op — in particular the ``_on_disconnect``
hook fires at most once per genuine ``CONNECTED → DISCONNECTED``
transition, never on a duplicate ``mark_disconnected`` while already
DISCONNECTED. This matters for at-least-once message delivery from
broker libraries that may call our ``on_disconnected`` listener twice
for the same network drop.

Subclasses MUST implement:

* :meth:`_send_heartbeat` — async, sends a single heartbeat ping to the
  remote. Raises an exception on failure; the exception type does not
  matter — :meth:`reconnect_loop` swallows it and waits the next backoff
  interval before retrying.
* :meth:`_on_disconnect` — async, called once per genuine disconnect.
  Used to flush pending state, emit an alert, etc. MUST NOT raise.

The reconnection loop (:meth:`reconnect_loop`) is a coroutine that
walks the canonical backoff sequence from :mod:`backoff`. The caller
schedules it as an :class:`asyncio.Task` after the first
``mark_disconnected`` and cancels the task when the adapter shuts down.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from enum import StrEnum

from iguanatrader.shared.backoff import backoff_seconds


class ConnectionState(StrEnum):
    """Discrete states of a long-lived live connection.

    Inherits :class:`enum.StrEnum` (Python 3.11+) so the value is
    JSON-serialisable for logging / SSE streams without a custom encoder.
    """

    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"


class HeartbeatMixin(ABC):
    """Mix in to any class that holds a live connection.

    The mixin owns one piece of state (``_state``) and a side-effect
    contract for transitions. It does not assume any particular network
    library; subclasses adapt it to ``ib_async``, ``python-telegram-bot``,
    ``hermes-client``, etc.

    Inherits :class:`abc.ABC` so that
    :meth:`_send_heartbeat` and :meth:`_on_disconnect` are enforced at
    instantiation time — a subclass that forgets to override either
    method raises :class:`TypeError` on construction (rather than
    failing at runtime when the unimplemented method is invoked).
    """

    _state: ConnectionState

    def __init__(self) -> None:
        self._state = ConnectionState.DISCONNECTED

    @property
    def state(self) -> ConnectionState:
        """Current connection state. Read-only — mutate via mark_* methods."""
        return self._state

    def mark_connected(self) -> None:
        """Transition to CONNECTED. Idempotent."""
        self._state = ConnectionState.CONNECTED

    def mark_reconnecting(self) -> None:
        """Transition to RECONNECTING. Idempotent."""
        self._state = ConnectionState.RECONNECTING

    async def mark_disconnected(self) -> None:
        """Transition to DISCONNECTED, firing :meth:`_on_disconnect` once.

        Idempotent: calling while already DISCONNECTED is a no-op (the
        ``_on_disconnect`` hook does NOT fire a second time).
        """
        if self._state is ConnectionState.DISCONNECTED:
            return
        self._state = ConnectionState.DISCONNECTED
        await self._on_disconnect()

    @abstractmethod
    async def _send_heartbeat(self) -> None:
        """Send one heartbeat ping. Raise on failure."""
        raise NotImplementedError

    @abstractmethod
    async def _on_disconnect(self) -> None:
        """Called exactly once per genuine CONNECTED→DISCONNECTED transition."""
        raise NotImplementedError

    async def reconnect_loop(self) -> None:
        """Walk the canonical backoff schedule attempting reconnect.

        Sets state to RECONNECTING, then repeatedly calls
        :meth:`_send_heartbeat`. On success, marks connected and
        returns. On failure, sleeps :func:`backoff_seconds` and retries.
        Runs forever until either it succeeds or the surrounding task
        is cancelled. Jitter is enabled by default.
        """
        self.mark_reconnecting()
        attempt = 0
        while True:
            try:
                await self._send_heartbeat()
            except Exception:
                delay = backoff_seconds(attempt, with_jitter=True)
                await asyncio.sleep(delay)
                attempt += 1
                continue
            self.mark_connected()
            return


__all__ = ["ConnectionState", "HeartbeatMixin"]
