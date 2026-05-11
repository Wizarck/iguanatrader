"""MultiChannelMessageDispatcher — per-channel routing with FR-isolation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import structlog

from iguanatrader.shared.channel_dispatch.protocol import MessageDispatcher
from iguanatrader.shared.channel_dispatch.types import (
    DispatchResult,
    OutboundMessage,
    Recipient,
)

log = structlog.get_logger("iguanatrader.shared.channel_dispatch.multi")


class MultiChannelMessageDispatcher:
    """Route each :class:`Recipient` to the dispatcher matching its ``channel``.

    Per-dispatcher try/except so a constructor-time crash or a runtime exception
    in one adapter cannot affect the rest. Recipients targeting an unknown
    channel are returned with ``status='skipped'`` and a descriptive error.
    """

    def __init__(self, dispatchers: Mapping[str, MessageDispatcher]) -> None:
        self._dispatchers: dict[str, MessageDispatcher] = dict(dispatchers)

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        # Group recipients by channel preserving original order within each group.
        by_channel: dict[str, list[Recipient]] = {}
        for r in recipients:
            by_channel.setdefault(r.channel, []).append(r)

        # Map each recipient to its result via address+channel key for stable
        # ordering reconstruction at the end.
        result_for: dict[tuple[str, str], DispatchResult] = {}

        for channel, group in by_channel.items():
            dispatcher = self._dispatchers.get(channel)
            if dispatcher is None:
                for r in group:
                    result_for[(r.channel, r.address)] = DispatchResult(
                        channel=r.channel,
                        address=r.address,
                        status="skipped",
                        wire_message_id=None,
                        error=f"no dispatcher for channel={channel!r}",
                    )
                continue

            try:
                group_results = await dispatcher.dispatch(message=message, recipients=group)
            except Exception as exc:
                log.warning(
                    "channel_dispatch.multi.dispatcher_failed",
                    channel=channel,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                for r in group:
                    result_for[(r.channel, r.address)] = DispatchResult(
                        channel=r.channel,
                        address=r.address,
                        status="failed",
                        wire_message_id=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                continue

            # Defensive: an honest dispatcher returns one result per recipient.
            # If it returns fewer, fill the gaps with a "failed" marker so the
            # invariant ``len(results) == len(recipients)`` holds.
            seen: set[tuple[str, str]] = set()
            for gr in group_results:
                key = (gr.channel, gr.address)
                result_for[key] = gr
                seen.add(key)
            for r in group:
                key = (r.channel, r.address)
                if key not in seen:
                    result_for[key] = DispatchResult(
                        channel=r.channel,
                        address=r.address,
                        status="failed",
                        wire_message_id=None,
                        error="dispatcher omitted result for this recipient",
                    )

        return [result_for[(r.channel, r.address)] for r in recipients]


__all__ = ["MultiChannelMessageDispatcher"]
