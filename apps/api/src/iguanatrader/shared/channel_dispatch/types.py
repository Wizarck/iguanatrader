"""Generic value types for outbound message dispatch.

Frozen dataclasses with ``slots=True`` for immutability + low overhead.
No iguanatrader-domain coupling; safe for upstream extraction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

DispatchStatus = Literal["delivered", "failed", "skipped"]


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """A single message ready to be fanned out to one or more recipients.

    Channel-agnostic — adapters render it to wire format (Telegram bot
    ``sendMessage`` body, WhatsApp ``messages`` payload, etc.).
    """

    body: str
    correlation_id: str
    metadata: Mapping[str, str] = field(default_factory=dict)
    subject: str | None = None
    #: Optional interactive actions rendered as channel-native buttons
    #: (Telegram inline keyboard; WhatsApp interactive — future). Each is
    #: ``(label, callback_data)``. Adapters that don't support buttons
    #: ignore it. Empty tuple = plain message.
    actions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Recipient:
    """A single addressable destination on a specific channel."""

    channel: str
    address: str
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """Outcome of a single ``(message, recipient)`` send attempt."""

    channel: str
    address: str
    status: DispatchStatus
    wire_message_id: str | None = None
    error: str | None = None


__all__ = [
    "DispatchResult",
    "DispatchStatus",
    "OutboundMessage",
    "Recipient",
]
