"""ChannelDispatcher Protocol + v1 LogOnly adapter (slice p1-followup-channel-fanout).

Wires the bus-driven ``ApprovalService._approval_requested_handler``
to a dispatcher after the ``create_request`` audit-write. Production
push to Telegram + Hermes is documented as a future operator slice
once per-tenant chat_id / phone_number config is plumbed + bot
tokens land in the SOPS bundles.

For v1 the daemon constructs ``LogOnlyChannelDispatcher`` (logs the
would-have-pushed event without making a real HTTP/bot call). The
Protocol shape lets a future slice swap in a concrete dispatcher
without changing the ApprovalService surface.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from iguanatrader.contexts.approval.channels.types import ApprovalRequestRow


log = structlog.get_logger("iguanatrader.contexts.approval.dispatcher")


@runtime_checkable
class ChannelDispatcher(Protocol):
    """Fan-out an ``ApprovalRequestRow`` to a list of channel names.

    Implementations MUST NOT raise on per-channel failures (FR32
    isolation); a bad channel must not skip the rest. The caller in
    ``ApprovalService`` further wraps the call in try/except so a
    completely-broken dispatcher (e.g. constructor-time import error)
    cannot bring down the audit-write path either.
    """

    async def fanout(
        self,
        *,
        request: ApprovalRequestRow,
        channels: list[str],
    ) -> None: ...


class LogOnlyChannelDispatcher:
    """v1 dispatcher: logs the would-have-pushed event; no real send.

    Used as the default daemon dispatcher when
    ``IGUANATRADER_CHANNEL_DISPATCHER`` is unset OR set to
    ``"log_only"``. Replacement candidates (future):

    * ``"telegram_hermes"`` - production push (Telegram bot send +
      Hermes WhatsApp HTTP). Requires per-tenant chat_id config + SOPS
      bundle for credentials.
    """

    async def fanout(
        self,
        *,
        request: ApprovalRequestRow,
        channels: list[str],
    ) -> None:
        log.info(
            "approval.channel.fanout.log_only",
            request_id=str(request.id),
            proposal_id=str(request.proposal_id),
            channels=list(channels),
            note="LogOnlyChannelDispatcher v1 - production push deferred",
        )


def build_channel_dispatcher_from_env() -> ChannelDispatcher:
    """Composition root for the daemon (slice p1-followup-channel-fanout §5).

    Returns ``LogOnlyChannelDispatcher`` when env-var unset / unknown.
    Future dispatchers register here once ops config (bot tokens,
    chat_id table, etc.) is ready.
    """
    kind = os.environ.get("IGUANATRADER_CHANNEL_DISPATCHER", "").strip().lower()
    if kind in {"", "log_only"}:
        return LogOnlyChannelDispatcher()
    log.warning(
        "approval.channel.dispatcher.unknown_kind",
        kind=kind,
        fallback="log_only",
    )
    return LogOnlyChannelDispatcher()


__all__ = [
    "ChannelDispatcher",
    "LogOnlyChannelDispatcher",
    "build_channel_dispatcher_from_env",
]
