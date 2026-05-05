"""Hermes / WhatsApp channel adapter — :class:`HermesWhatsAppChannel`.

Mirrors :class:`TelegramChannel` shape — same :class:`ChannelPort`
inheritance, same :class:`HeartbeatMixin` heritage, same canonical
backoff. The only differences are wire-format details (Meta Cloud
API webhook vs Telegram long-poll) which are entirely encapsulated
inside the transport (D8).

FR37 invariant: per spec ``approval`` Requirement 1 the user-visible
behaviour MUST be byte-for-byte identical with Telegram (modulo
channel field on the audit row).
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

import structlog

from iguanatrader.contexts.approval.channels.base import ChannelPort
from iguanatrader.contexts.approval.channels.command_handler import dispatch
from iguanatrader.contexts.approval.channels.transports.base import (
    ChannelTransportPort,
)
from iguanatrader.contexts.approval.channels.types import (
    ApprovalRequestRow,
    IncomingCommand,
)
from iguanatrader.contexts.approval.repository import ApprovalRepository

log = structlog.get_logger("iguanatrader.contexts.approval.channels.whatsapp_hermes")


class HermesWhatsAppChannel(ChannelPort):
    """Hermes / Meta Cloud API WhatsApp adapter."""

    def __init__(
        self,
        *,
        transport: ChannelTransportPort,
        repository: ApprovalRepository,
        service: Any,
        message_bus: Any,
        tenant_id: UUID,
    ) -> None:
        super().__init__()
        self._transport = transport
        self._repository = repository
        self._service = service
        self._message_bus = message_bus
        self._tenant_id = tenant_id
        self._stopped: bool = False

    async def deliver_request(
        self,
        request: ApprovalRequestRow,
        recipient: Any,
    ) -> None:
        body = (
            f"Approve trade proposal {request.proposal_id}? "
            f"expires_at={request.expires_at.isoformat()}"
        )
        message_id = await self._transport.send_message(
            recipient=str(recipient),
            content=body,
        )
        log.info(
            "approval.channel.whatsapp.delivered",
            request_id=str(request.id),
            whatsapp_message_id=message_id,
        )

    async def start_listening(self) -> None:
        if self._stopped:
            return
        updates = await self._transport.fetch_updates()
        for inbound in updates:
            await self._handle_inbound(inbound)

    async def stop(self) -> None:
        self._stopped = True
        await self.mark_disconnected()

    async def _send_heartbeat(self) -> None:
        ok = await self._transport.health_check()
        if not ok:
            raise RuntimeError("hermes transport reported unhealthy")

    async def _on_disconnect(self) -> None:
        log.warning("approval.channel.whatsapp.disconnected")

    async def _handle_inbound(self, inbound: IncomingCommand) -> None:
        authorized, sender_db_id = await self._repository.is_sender_authorized(
            tenant_id=self._tenant_id,
            channel="whatsapp",
            external_id=inbound.sender_external_id,
        )
        if not authorized:
            external_hash = hashlib.sha256(inbound.sender_external_id.encode("utf-8")).hexdigest()
            log.info(
                "approval.channel.sender_rejected",
                channel="whatsapp",
                external_id_sha256=external_hash,
                tenant_id=str(self._tenant_id),
            )
            return
        normalised = IncomingCommand(
            command_name=inbound.command_name,
            raw_args=inbound.raw_args,
            sender_external_id=inbound.sender_external_id,
            channel="whatsapp",
            tenant_id=self._tenant_id,
            idempotency_key=inbound.idempotency_key,
            request_id=inbound.request_id,
            sender_db_id=sender_db_id,
            user_db_id=None,
            role=inbound.role,
        )
        await dispatch(
            normalised,
            service=self._service,
            message_bus=self._message_bus,
            repository=self._repository,
        )


__all__ = ["HermesWhatsAppChannel"]
