"""ChannelDispatcher binding layer + composition root.

Two coexisting Protocols:

* **Legacy** ``ChannelDispatcher.fanout(request, channels)`` — the
  approval-context-coupled facade introduced by slice
  ``p1-followup-channel-fanout`` (PR #111). Consumed by
  :class:`ApprovalService._approval_requested_handler`.
* **Generic** :class:`iguanatrader.shared.channel_dispatch.MessageDispatcher`
  (``dispatch(message, recipients)``) — the upstream-extractable core
  shipped by slice ``p1-channel-fanout-production``.

Adapters in this module map between the two:

* :func:`build_outbound_message_from_request` — ``ApprovalRequestRow`` →
  :class:`OutboundMessage`.
* :func:`resolve_recipients_from_request` — looks up enabled
  ``authorized_senders`` rows for the request's tenant + channels and
  projects them to :class:`Recipient`.
* :class:`_MessageDispatcherChannelAdapter` — wraps a generic
  ``MessageDispatcher`` so it can be plugged into the legacy
  ``ChannelDispatcher`` slot without changing the
  :class:`ApprovalService` surface.

The composition root :func:`build_channel_dispatcher_from_env` keeps the
default ``LogOnlyChannelDispatcher`` fallback (existing behaviour) and
adds a ``telegram_hermes`` kind that constructs the production
generic-core stack from env vars. Missing credentials → log + fallback
(no crash); the daemon stays up so the operator can wire SOPS bundles
without code changes.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

from iguanatrader.shared.channel_dispatch import (
    MessageDispatcher,
    MultiChannelMessageDispatcher,
    OutboundMessage,
    Recipient,
)
from iguanatrader.shared.channel_dispatch.adapters import (
    HermesWhatsAppMessageDispatcher,
    TelegramBotMessageDispatcher,
)

if TYPE_CHECKING:
    from iguanatrader.contexts.approval.channels.types import ApprovalRequestRow
    from iguanatrader.contexts.approval.repository import ApprovalRepository


log = structlog.get_logger("iguanatrader.contexts.approval.dispatcher")


@runtime_checkable
class ChannelDispatcher(Protocol):
    """Approval-context fanout facade (legacy shape, slice
    ``p1-followup-channel-fanout``).

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

    Default when ``IGUANATRADER_CHANNEL_DISPATCHER`` is unset / unknown
    / set to ``"log_only"``. Kept as a discrete class (not via the
    generic core wrapper) so the legacy log event
    ``approval.channel.fanout.log_only`` continues to fire with the
    same shape — existing dashboards and tests rely on it.
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


def build_outbound_message_from_request(request: ApprovalRequestRow) -> OutboundMessage:
    """Render an :class:`ApprovalRequestRow` into a generic
    :class:`OutboundMessage`.

    Body shape matches the existing :class:`TelegramChannel` /
    :class:`HermesWhatsAppChannel` adapters from P1 archive — operators
    see byte-identical text whether the message arrives via the dashboard
    bus path (this slice) or via the legacy dashboard-driven push.
    """
    body = (
        f"Approve trade proposal {request.proposal_id}? "
        f"expires_at={request.expires_at.isoformat()}"
    )
    return OutboundMessage(
        body=body,
        correlation_id=str(request.id),
        metadata={
            "proposal_id": str(request.proposal_id),
            "tenant_id": str(request.tenant_id),
        },
    )


async def resolve_recipients_from_request(
    request: ApprovalRequestRow,
    repository: ApprovalRepository,
) -> list[Recipient]:
    """Look up enabled ``authorized_senders`` for the request's tenant + channels.

    Returns one :class:`Recipient` per ``(channel, external_id)`` pair.
    Channels listed in ``request.delivered_to_channels`` that have zero
    matching senders simply contribute zero recipients (the dispatcher
    later records nothing for them; nothing to deliver).
    """
    rows = await repository.list_enabled_senders(
        tenant_id=request.tenant_id,
        channels=list(request.delivered_to_channels),
    )
    return [
        Recipient(
            channel=row.channel,
            address=row.external_id,
            display_name=row.display_name,
        )
        for row in rows
    ]


class _MessageDispatcherChannelAdapter:
    """Adapt a generic :class:`MessageDispatcher` to the legacy
    :class:`ChannelDispatcher` shape.

    On ``fanout``:

    1. Build :class:`OutboundMessage` from the request.
    2. Resolve :class:`Recipient` list via the repository.
    3. Invoke ``inner.dispatch(message=, recipients=)``.
    4. Log each :class:`DispatchResult` for observability.

    Wraps step 2 + step 3 in a try/except so per-recipient transport
    failures cannot escape (FR32 isolation; defense in depth with the
    outer try/except in :class:`ApprovalService`).
    """

    def __init__(
        self,
        *,
        inner: MessageDispatcher,
        repository: ApprovalRepository,
    ) -> None:
        self._inner = inner
        self._repository = repository

    async def fanout(
        self,
        *,
        request: ApprovalRequestRow,
        channels: list[str],
    ) -> None:
        message = build_outbound_message_from_request(request)
        try:
            recipients = await resolve_recipients_from_request(request, self._repository)
        except Exception as exc:
            log.warning(
                "approval.channel.dispatch.recipient_resolution_failed",
                request_id=str(request.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return

        if not recipients:
            log.info(
                "approval.channel.dispatch.no_recipients",
                request_id=str(request.id),
                channels=list(channels),
            )
            return

        results = await self._inner.dispatch(message=message, recipients=recipients)
        for r in results:
            log.info(
                "approval.channel.dispatch.result",
                request_id=str(request.id),
                **asdict(r),
            )


def _build_telegram_hermes_from_env(
    repository: ApprovalRepository,
) -> ChannelDispatcher:
    """Construct the production telegram + hermes stack from env vars.

    Falls back to :class:`LogOnlyChannelDispatcher` if any required
    credential is missing (the daemon stays up + the gap is visible via
    structured logs; operator wires SOPS bundle without code changes).
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    hermes_url = os.environ.get("HERMES_BASE_URL", "").strip()
    hermes_secret = os.environ.get("HERMES_HMAC_SECRET", "").strip()
    missing: list[str] = []
    if not bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not hermes_url:
        missing.append("HERMES_BASE_URL")
    if not hermes_secret:
        missing.append("HERMES_HMAC_SECRET")
    if missing:
        log.error(
            "approval.channel.dispatcher.missing_credentials",
            missing=missing,
            fallback="log_only",
        )
        return LogOnlyChannelDispatcher()

    telegram = TelegramBotMessageDispatcher(bot_token=bot_token)
    hermes = HermesWhatsAppMessageDispatcher(
        base_url=hermes_url,
        hmac_secret=hermes_secret.encode("utf-8"),
    )
    multi = MultiChannelMessageDispatcher(dispatchers={"telegram": telegram, "whatsapp": hermes})
    return _MessageDispatcherChannelAdapter(inner=multi, repository=repository)


def build_channel_dispatcher_from_env(
    repository: ApprovalRepository | None = None,
) -> ChannelDispatcher:
    """Composition root for the daemon.

    Resolution table:

    +-------------------------------------------+-----------------------+
    | ``IGUANATRADER_CHANNEL_DISPATCHER``       | Result                |
    +===========================================+=======================+
    | unset / ``""`` / ``"log_only"``           | LogOnly fallback      |
    +-------------------------------------------+-----------------------+
    | ``"telegram_hermes"`` (repository set,    | Production multi      |
    | all credentials present)                  | dispatcher            |
    +-------------------------------------------+-----------------------+
    | ``"telegram_hermes"`` (any missing piece) | LogOnly + error log   |
    +-------------------------------------------+-----------------------+
    | any other value                           | LogOnly + warn log    |
    +-------------------------------------------+-----------------------+

    The ``repository`` argument is required only for ``telegram_hermes``;
    callers using the default LogOnly path may omit it for backward
    compatibility with the slice ``p1-followup-channel-fanout`` signature.
    """
    kind = os.environ.get("IGUANATRADER_CHANNEL_DISPATCHER", "").strip().lower()
    if kind in {"", "log_only"}:
        return LogOnlyChannelDispatcher()
    if kind == "telegram_hermes":
        if repository is None:
            log.error(
                "approval.channel.dispatcher.no_repository",
                fallback="log_only",
                hint="pass repository=ApprovalRepository() to build_channel_dispatcher_from_env",
            )
            return LogOnlyChannelDispatcher()
        return _build_telegram_hermes_from_env(repository)
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
    "build_outbound_message_from_request",
    "resolve_recipients_from_request",
]
