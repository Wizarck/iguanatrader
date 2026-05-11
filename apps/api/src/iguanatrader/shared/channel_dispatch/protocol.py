"""Protocols for the generic dispatch core.

Two narrow Protocols, each the smallest possible surface:

* :class:`MessageDispatcher` — fanout-level: send one message to N recipients.
* :class:`OutboundTransport` — wire-level: send one body to one address.

Both are ``runtime_checkable`` so callers may ``isinstance(x, MessageDispatcher)``
in defensive composition roots.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from iguanatrader.shared.channel_dispatch.types import (
    DispatchResult,
    OutboundMessage,
    Recipient,
)


@runtime_checkable
class MessageDispatcher(Protocol):
    """Fanout abstraction.

    Implementations MUST NOT raise — per-recipient failures are returned as
    :class:`DispatchResult` with ``status='failed'`` and a populated ``error``.
    The caller decides whether to log, persist, or retry.
    """

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]: ...


@runtime_checkable
class OutboundTransport(Protocol):
    """Wire-level send.

    Returns the wire message id on success. May raise on transport error;
    the calling adapter MUST translate the exception into a failed
    :class:`DispatchResult`.
    """

    async def send(self, *, address: str, body: str) -> str: ...


@runtime_checkable
class RateLimiter(Protocol):
    """Async-safe rate limiter contract — :class:`AsyncTokenBucket` is
    the canonical implementation; tests inject lightweight fakes."""

    async def acquire(self) -> None: ...


__all__ = [
    "MessageDispatcher",
    "OutboundTransport",
    "RateLimiter",
]
