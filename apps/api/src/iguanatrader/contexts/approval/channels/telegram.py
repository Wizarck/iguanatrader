"""Telegram channel adapter — :class:`TelegramChannel`.

Per slice P1 design D1 + D3: subclasses :class:`ChannelPort` and
inherits :class:`HeartbeatMixin`. The transport itself is stubbed via
:class:`ChannelTransportPort` (D8) — at this slice the production
adapter accepts a :class:`FakeTelegramTransport` for tests; a follow-up
slice swaps in the real ``python-telegram-bot`` Bot.
"""

from __future__ import annotations

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
from iguanatrader.shared.contextvars import with_tenant_context

log = structlog.get_logger("iguanatrader.contexts.approval.channels.telegram")


class TelegramChannel(ChannelPort):
    """Telegram bot adapter — long-poll inbound + render outbound."""

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

    # ------------------------------------------------------------------ ChannelPort
    async def deliver_request(
        self,
        request: ApprovalRequestRow,
        recipient: Any,
    ) -> None:
        """Render a clear buy/sell approval prompt + send via the transport."""
        body = await self._render_request_body(request)
        message_id = await self._transport.send_message(
            recipient=str(recipient),
            content=body,
        )
        log.info(
            "approval.channel.telegram.delivered",
            request_id=str(request.id),
            telegram_message_id=message_id,
        )

    async def _render_request_body(self, request: ApprovalRequestRow) -> str:
        """Load the proposal levels + render the side-aware card.

        Best-effort: any failure loading the proposal falls back to a
        terse prompt so delivery is never blocked by a render error.
        """
        terse = (
            f"Aprobar propuesta {request.proposal_id}? "
            f"/approve {request.id}  ·  expira {request.expires_at.isoformat()}"
        )
        # Exit-approval rows (WS-5 PR-B) carry no proposal_id; deliver the terse
        # body (with the /approve link) — the rich exit card is rendered by the
        # dispatcher fan-out path.
        if request.proposal_id is None:
            return terse
        try:
            from iguanatrader.contexts.approval.channels.proposal_card import (
                render_proposal_card,
            )
            from iguanatrader.contexts.trading.repository import (
                TradeProposalRepository,
            )

            proposal = await TradeProposalRepository().get_by_id(request.proposal_id)
            if proposal is None:
                return terse
            return render_proposal_card(
                request_id=request.id,
                proposal_id=request.proposal_id,
                symbol=proposal.symbol,
                side=proposal.side,
                quantity=proposal.quantity,
                entry_price=proposal.entry_price_indicative,
                stop_price=proposal.stop_price,
                target_price=proposal.target_price,
                expires_at=request.expires_at,
                reasoning=proposal.reasoning,
            )
        except Exception:  # never block delivery on a render error
            log.warning(
                "approval.channel.telegram.card_render_failed",
                request_id=str(request.id),
                proposal_id=str(request.proposal_id),
                exc_info=True,
            )
            return terse

    async def start_listening(self) -> None:
        """Drain one batch of inbound updates + dispatch through command_handler.

        For tests the caller calls this in a loop; production wires
        the real long-poll loop in the follow-up real-clients slice.
        """
        if self._stopped:
            return
        updates = await self._transport.fetch_updates()
        for inbound in updates:
            await self._handle_inbound(inbound)

    async def stop(self) -> None:
        self._stopped = True
        await self.mark_disconnected()

    # ------------------------------------------------------------------ HeartbeatMixin hooks
    async def _send_heartbeat(self) -> None:
        # The transport raises on failure; we propagate so the
        # reconnect_loop sleeps + retries per the canonical backoff.
        ok = await self._transport.health_check()
        if not ok:
            raise RuntimeError("telegram transport reported unhealthy")

    async def _on_disconnect(self) -> None:
        log.warning("approval.channel.telegram.disconnected")

    # ------------------------------------------------------------------ helpers
    async def _handle_inbound(self, inbound: IncomingCommand) -> None:
        """Verify the sender + dispatch through command_handler."""
        authorized, sender_db_id = await self._repository.is_sender_authorized(
            tenant_id=self._tenant_id,
            channel="telegram",
            external_id=inbound.sender_external_id,
        )
        if not authorized:
            # D6: silent-drop + structlog. NEVER echo to the user.
            import hashlib

            external_hash = hashlib.sha256(inbound.sender_external_id.encode("utf-8")).hexdigest()
            log.info(
                "approval.channel.sender_rejected",
                channel="telegram",
                external_id_sha256=external_hash,
                tenant_id=str(self._tenant_id),
            )
            return
        # Stamp the resolved DB id so the dispatcher can pass it to
        # the handler (records into approval_decisions).
        normalised = IncomingCommand(
            command_name=inbound.command_name,
            raw_args=inbound.raw_args,
            sender_external_id=inbound.sender_external_id,
            channel="telegram",
            tenant_id=self._tenant_id,
            idempotency_key=inbound.idempotency_key,
            request_id=inbound.request_id,
            sender_db_id=sender_db_id,
            user_db_id=None,
            # #32: role is NOT taken from the transport-supplied inbound
            # command — a crafted Telegram message could otherwise claim
            # role="admin" and run admin-only commands (/halt, /override).
            # Bot channels are pinned to "user"; admin commands flow only
            # through the JWT-backed dashboard channel (gotcha #50). A DB
            # `authorized_senders.role` column can later raise a verified
            # sender to admin, but never the wire payload.
            role="user",
        )
        # #33: bind the bot-token's tenant for the whole dispatch so the
        # get_request / record_decision reads+writes are tenant-scoped by
        # the persistence listener (the inbound path has no request scope
        # that would otherwise set tenant_id_var).
        async with with_tenant_context(self._tenant_id):
            await dispatch(
                normalised,
                service=self._service,
                message_bus=self._message_bus,
                repository=self._repository,
            )


__all__ = ["TelegramChannel"]
