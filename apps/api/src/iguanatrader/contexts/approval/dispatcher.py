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
from collections.abc import Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

from iguanatrader.shared.channel_dispatch import (
    LogOnlyMessageDispatcher,
    MessageDispatcher,
    MultiChannelMessageDispatcher,
    OutboundMessage,
    Recipient,
)
from iguanatrader.shared.channel_dispatch.adapters import (
    EmailSMTPDispatcher,
    HermesWhatsAppMessageDispatcher,
    TelegramBotMessageDispatcher,
)
from iguanatrader.shared.channel_dispatch.adapters.email_smtp import (
    EMAIL_CHANNEL,
    EMAIL_DEFAULT_FROM_ADDRESS,
    EMAIL_DEFAULT_FROM_NAME,
    EMAIL_DEFAULT_PORT,
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


def _build_telegram_from_env() -> MessageDispatcher | None:
    """Return a Telegram dispatcher if ``TELEGRAM_BOT_TOKEN`` is set; else None.

    Per-channel fallback: a missing token disables Telegram only — other
    channels in the same selector keep running.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        log.error(
            "approval.channel.dispatcher.missing_credentials",
            channel="telegram",
            missing=["TELEGRAM_BOT_TOKEN"],
            fallback="log_only",
        )
        return None
    return TelegramBotMessageDispatcher(bot_token=bot_token)


def _build_hermes_from_env() -> MessageDispatcher | None:
    """Return a Hermes/WhatsApp dispatcher if both env vars are set."""
    hermes_url = os.environ.get("HERMES_BASE_URL", "").strip()
    hermes_secret = os.environ.get("HERMES_HMAC_SECRET", "").strip()
    missing: list[str] = []
    if not hermes_url:
        missing.append("HERMES_BASE_URL")
    if not hermes_secret:
        missing.append("HERMES_HMAC_SECRET")
    if missing:
        log.error(
            "approval.channel.dispatcher.missing_credentials",
            channel="whatsapp",
            missing=missing,
            fallback="log_only",
        )
        return None
    return HermesWhatsAppMessageDispatcher(
        base_url=hermes_url,
        hmac_secret=hermes_secret.encode("utf-8"),
    )


def _build_email_from_env() -> MessageDispatcher | None:
    """Return an :class:`EmailSMTPDispatcher` if required SMTP creds are set."""
    host = os.environ.get("IGUANATRADER_SMTP_HOST", "").strip()
    username = os.environ.get("IGUANATRADER_SMTP_USERNAME", "").strip()
    password = os.environ.get("IGUANATRADER_SMTP_PASSWORD", "").strip()
    missing: list[str] = []
    if not host:
        missing.append("IGUANATRADER_SMTP_HOST")
    if not username:
        missing.append("IGUANATRADER_SMTP_USERNAME")
    if not password:
        missing.append("IGUANATRADER_SMTP_PASSWORD")
    if missing:
        log.error(
            "approval.channel.dispatcher.missing_credentials",
            channel="email",
            missing=missing,
            fallback="log_only",
        )
        return None
    port_raw = os.environ.get("IGUANATRADER_SMTP_PORT", "").strip()
    try:
        port = int(port_raw) if port_raw else EMAIL_DEFAULT_PORT
    except ValueError:
        log.warning(
            "approval.channel.dispatcher.invalid_smtp_port",
            value=port_raw,
            fallback=EMAIL_DEFAULT_PORT,
        )
        port = EMAIL_DEFAULT_PORT
    from_address = (
        os.environ.get("IGUANATRADER_SMTP_FROM_ADDRESS", "").strip() or EMAIL_DEFAULT_FROM_ADDRESS
    )
    from_name = os.environ.get("IGUANATRADER_SMTP_FROM_NAME", "").strip() or EMAIL_DEFAULT_FROM_NAME
    use_tls_raw = os.environ.get("IGUANATRADER_SMTP_USE_TLS", "true").strip().lower()
    use_tls = use_tls_raw not in {"0", "false", "no", "off"}
    return EmailSMTPDispatcher(
        host=host,
        port=port,
        username=username,
        password=password,
        from_address=from_address,
        from_name=from_name,
        use_tls=use_tls,
    )


def _compose_multi_dispatcher(
    *,
    repository: ApprovalRepository,
    parts: dict[str, MessageDispatcher | None],
) -> ChannelDispatcher:
    """Wrap the live subset of channel dispatchers; LogOnly if all fall back."""
    live = {channel: d for channel, d in parts.items() if d is not None}
    if not live:
        log.error(
            "approval.channel.dispatcher.all_channels_disabled",
            requested=sorted(parts.keys()),
            fallback="log_only",
        )
        return LogOnlyChannelDispatcher()
    multi = MultiChannelMessageDispatcher(dispatchers=live)
    return _MessageDispatcherChannelAdapter(inner=multi, repository=repository)


def _build_telegram_hermes_from_env(
    repository: ApprovalRepository,
) -> ChannelDispatcher:
    """Construct the telegram + hermes stack with per-channel fallback."""
    return _compose_multi_dispatcher(
        repository=repository,
        parts={
            "telegram": _build_telegram_from_env(),
            "whatsapp": _build_hermes_from_env(),
        },
    )


def _build_telegram_hermes_email_from_env(
    repository: ApprovalRepository,
) -> ChannelDispatcher:
    """Telegram + Hermes + Email with per-channel fallback."""
    return _compose_multi_dispatcher(
        repository=repository,
        parts={
            "telegram": _build_telegram_from_env(),
            "whatsapp": _build_hermes_from_env(),
            EMAIL_CHANNEL: _build_email_from_env(),
        },
    )


def _build_email_only_from_env(
    repository: ApprovalRepository,
) -> ChannelDispatcher:
    """Email-only path — for tenants without Telegram/Hermes wiring."""
    return _compose_multi_dispatcher(
        repository=repository,
        parts={EMAIL_CHANNEL: _build_email_from_env()},
    )


def build_channel_dispatcher_from_env(
    repository: ApprovalRepository | None = None,
) -> ChannelDispatcher:
    """Composition root for the daemon.

    Resolution table:

    +--------------------------------------------------+-----------------------+
    | ``IGUANATRADER_CHANNEL_DISPATCHER``              | Result                |
    +==================================================+=======================+
    | unset / ``""`` / ``"log_only"``                  | LogOnly fallback      |
    +--------------------------------------------------+-----------------------+
    | ``"telegram_hermes"`` (repository set)           | Telegram + Hermes     |
    +--------------------------------------------------+-----------------------+
    | ``"telegram_hermes_email"`` (repository set)     | Telegram + Hermes +   |
    |                                                  | Email                 |
    +--------------------------------------------------+-----------------------+
    | ``"email"`` (repository set)                     | Email only            |
    +--------------------------------------------------+-----------------------+
    | any other value                                  | LogOnly + warn log    |
    +--------------------------------------------------+-----------------------+

    Per-channel fallback: a missing credential for one channel falls back to
    log-only individually; remaining channels stay live. If every requested
    channel is missing creds → :class:`LogOnlyChannelDispatcher`.

    The ``repository`` argument is required for every selector other than
    ``log_only`` / unset; callers using the default LogOnly path may omit it.
    """
    kind = os.environ.get("IGUANATRADER_CHANNEL_DISPATCHER", "").strip().lower()
    if kind in {"", "log_only"}:
        return LogOnlyChannelDispatcher()
    builders: dict[str, Callable[[ApprovalRepository], ChannelDispatcher]] = {
        "telegram_hermes": _build_telegram_hermes_from_env,
        "telegram_hermes_email": _build_telegram_hermes_email_from_env,
        "email": _build_email_only_from_env,
    }
    if kind not in builders:
        log.warning(
            "approval.channel.dispatcher.unknown_kind",
            kind=kind,
            fallback="log_only",
        )
        return LogOnlyChannelDispatcher()
    if repository is None:
        log.error(
            "approval.channel.dispatcher.no_repository",
            kind=kind,
            fallback="log_only",
            hint="pass repository=ApprovalRepository() to build_channel_dispatcher_from_env",
        )
        return LogOnlyChannelDispatcher()
    return builders[kind](repository)


def _compose_user_multi_dispatcher(
    parts: dict[str, MessageDispatcher | None],
) -> MessageDispatcher:
    """Wrap the live subset of channel dispatchers for the user-context path.

    Mirrors :func:`_compose_multi_dispatcher` but returns the generic
    :class:`MessageDispatcher` shape (``dispatch(message, recipients)``)
    instead of the approval-context :class:`ChannelDispatcher`
    (``fanout(request, channels)``). The forgot-password endpoint — and
    any future flow that fans to a single user without going through the
    ``authorized_senders`` table — calls this directly.
    """
    live = {channel: d for channel, d in parts.items() if d is not None}
    if not live:
        log.error(
            "user.channel.dispatcher.all_channels_disabled",
            requested=sorted(parts.keys()),
            fallback="log_only",
        )
        return LogOnlyMessageDispatcher()
    return MultiChannelMessageDispatcher(dispatchers=live)


def build_user_channel_dispatcher_from_env() -> MessageDispatcher:
    """Composition root for flows that dispatch to a single user record.

    The forgot-password endpoint (slice ``auth-forgot-password-flow``)
    consumes this factory. Unlike :func:`build_channel_dispatcher_from_env`,
    this variant does NOT require an :class:`ApprovalRepository`
    because the recipient list is computed from the user record itself
    (see :func:`iguanatrader.shared.channel_dispatch.recipients.resolve_recipients_for_user`),
    not from the ``authorized_senders`` table.

    Resolution mirrors :func:`build_channel_dispatcher_from_env`:

    +--------------------------------------------------+-----------------------+
    | ``IGUANATRADER_CHANNEL_DISPATCHER``              | Result                |
    +==================================================+=======================+
    | unset / ``""`` / ``"log_only"``                  | LogOnly fallback      |
    +--------------------------------------------------+-----------------------+
    | ``"telegram_hermes"``                            | Telegram + Hermes     |
    +--------------------------------------------------+-----------------------+
    | ``"telegram_hermes_email"``                      | Telegram + Hermes +   |
    |                                                  | Email                 |
    +--------------------------------------------------+-----------------------+
    | ``"email"``                                      | Email only            |
    +--------------------------------------------------+-----------------------+
    | any other value                                  | LogOnly + warn log    |
    +--------------------------------------------------+-----------------------+

    Per-channel fallback: a missing credential for one channel falls back
    to skipping that channel individually; remaining channels stay live.
    If every requested channel is missing creds →
    :class:`LogOnlyMessageDispatcher`.
    """
    kind = os.environ.get("IGUANATRADER_CHANNEL_DISPATCHER", "").strip().lower()
    if kind in {"", "log_only"}:
        return LogOnlyMessageDispatcher()
    if kind == "telegram_hermes":
        return _compose_user_multi_dispatcher(
            {
                "telegram": _build_telegram_from_env(),
                "whatsapp": _build_hermes_from_env(),
            }
        )
    if kind == "telegram_hermes_email":
        return _compose_user_multi_dispatcher(
            {
                "telegram": _build_telegram_from_env(),
                "whatsapp": _build_hermes_from_env(),
                EMAIL_CHANNEL: _build_email_from_env(),
            }
        )
    if kind == "email":
        return _compose_user_multi_dispatcher(
            {EMAIL_CHANNEL: _build_email_from_env()},
        )
    log.warning(
        "user.channel.dispatcher.unknown_kind",
        kind=kind,
        fallback="log_only",
    )
    return LogOnlyMessageDispatcher()


__all__ = [
    "ChannelDispatcher",
    "LogOnlyChannelDispatcher",
    "build_channel_dispatcher_from_env",
    "build_outbound_message_from_request",
    "build_user_channel_dispatcher_from_env",
    "resolve_recipients_from_request",
]
