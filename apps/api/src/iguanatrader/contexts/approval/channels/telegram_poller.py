"""Telegram inbound long-poll — turns button taps into approve/reject.

The daemon's only Telegram-inbound component. Telegram bot ``getUpdates``
long-poll for ``callback_query`` updates; each tap carries
``callback_data`` of the form ``approve:{request_id}`` /
``reject:{request_id}`` set by the outbound card's inline keyboard
(:func:`build_outbound_message_from_request`).

Flow per tap:

1. **Owner gate (fail-closed).** The tapper's Telegram user id must match
   an *enabled* ``authorized_senders`` row for the tenant
   (:meth:`ApprovalRepository.resolve_enabled_sender`). Any miss → the tap
   is acknowledged with "No autorizado" and nothing happens.
2. **Route to the canonical dispatcher.** A normalised
   :class:`IncomingCommand` (``/approve`` / ``/reject``, ``request_id``)
   flows through :func:`command_handler.dispatch`, so the button shares the
   exact handlers, idempotency window and execution bridge as a typed
   command — recording a *granted* decision publishes ``ProposalApproved``
   which the trading context turns into a real (bracketed) order.
3. **Acknowledge + edit.** ``answerCallbackQuery`` clears the spinner and
   the card is edited with a "✅ Aprobado y ejecutado" / "❌ Rechazado"
   footer so the operator sees the outcome inline.

The whole dispatch runs inside :func:`run_in_session_scope` so the decision
commits and its events publish-after-commit (audit #2/#27/#29).
"""

from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import UUID

import httpx
import structlog

from iguanatrader.contexts.approval.channels.command_handler import dispatch
from iguanatrader.contexts.approval.channels.types import (
    CommandResult,
    IncomingCommand,
    RequiredRole,
)
from iguanatrader.shared.contextvars import run_in_session_scope

log = structlog.get_logger("iguanatrader.contexts.approval.channels.telegram_poller")

#: callback_data action prefix → canonical command name.
_ACTION_COMMANDS: dict[str, str] = {"approve": "/approve", "reject": "/reject"}

#: Back-off before retrying after a transient ``getUpdates`` failure.
_POLL_BACKOFF_SECONDS: float = 3.0


class TelegramCallbackPoller:
    """Long-poll ``getUpdates`` and route ``callback_query`` taps to commands."""

    def __init__(
        self,
        *,
        bot_token: str,
        tenant_id: UUID,
        service: Any,
        message_bus: Any,
        repository: Any,
        session_factory: Any,
        client: httpx.AsyncClient | None = None,
        poll_timeout: int = 25,
    ) -> None:
        self._base = f"https://api.telegram.org/bot{bot_token}"
        self._tenant_id = tenant_id
        self._service = service
        self._bus = message_bus
        self._repository = repository
        self._session_factory = session_factory
        self._client = client or httpx.AsyncClient(timeout=float(poll_timeout) + 10.0)
        self._owns_client = client is None
        self._poll_timeout = poll_timeout
        self._offset = 0
        self._stopped = False

    async def run(self) -> None:
        """Long-poll until :meth:`stop`. Never raises out of the loop body."""
        log.info("approval.telegram_poller.started", tenant_id=str(self._tenant_id))
        while not self._stopped:
            try:
                updates = await self._get_updates()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # transient network/API error → back off, keep polling
                log.warning("approval.telegram_poller.poll_failed", error=str(exc))
                await asyncio.sleep(_POLL_BACKOFF_SECONDS)
                continue
            for upd in updates:
                self._offset = max(self._offset, int(upd.get("update_id", 0)) + 1)
                cq = upd.get("callback_query")
                if not cq:
                    continue
                try:
                    await self._handle_callback(cast("dict[str, Any]", cq))
                except Exception as exc:  # one bad tap must not kill the loop
                    log.warning("approval.telegram_poller.callback_failed", error=str(exc))
        log.info("approval.telegram_poller.stopped", tenant_id=str(self._tenant_id))

    async def stop(self) -> None:
        self._stopped = True
        if self._owns_client:
            await self._client.aclose()

    async def _get_updates(self) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeout": self._poll_timeout,
            "allowed_updates": '["callback_query"]',
        }
        if self._offset:
            params["offset"] = self._offset
        resp = await self._client.get(f"{self._base}/getUpdates", params=params)
        resp.raise_for_status()
        payload = cast("dict[str, Any]", resp.json())
        if not payload.get("ok"):
            raise RuntimeError(f"getUpdates not ok: {payload}")
        return list(payload.get("result", []))

    async def _handle_callback(self, cq: dict[str, Any]) -> None:
        cq_id = str(cq.get("id", ""))
        data = str(cq.get("data", ""))
        from_id = str((cq.get("from") or {}).get("id", ""))
        msg = cast("dict[str, Any]", cq.get("message") or {})
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        message_id = msg.get("message_id")
        original_text = str(msg.get("text", ""))

        action, _, rid_str = data.partition(":")
        command_name = _ACTION_COMMANDS.get(action)
        if command_name is None or not rid_str:
            await self._answer(cq_id, "Acción no reconocida.")
            return
        try:
            request_id = UUID(rid_str)
        except ValueError:
            await self._answer(cq_id, "Identificador inválido.")
            return

        async def _do() -> CommandResult | None:
            resolved = await self._repository.resolve_enabled_sender(
                tenant_id=self._tenant_id,
                channel="telegram",
                external_id=from_id,
            )
            if resolved is None:
                return None  # owner gate, fail-closed
            incoming = IncomingCommand(
                command_name=command_name,
                raw_args="",
                sender_external_id=from_id,
                channel="telegram",
                tenant_id=self._tenant_id,
                idempotency_key=cq_id,
                request_id=request_id,
                sender_db_id=resolved.id,
                role=cast("RequiredRole", resolved.role),
            )
            return await dispatch(
                incoming,
                service=self._service,
                message_bus=self._bus,
                repository=self._repository,
            )

        result = cast(
            "CommandResult | None",
            await run_in_session_scope(self._session_factory, self._bus, self._tenant_id, _do),
        )

        if result is None:
            log.warning("approval.telegram_poller.unauthorized", from_id=from_id, data=data)
            await self._answer(cq_id, "No autorizado.")
            return

        succeeded = result.status == "ok"
        if not succeeded:
            await self._answer(cq_id, result.message or "No se pudo procesar.")
            return

        footer = "✅ Aprobado y ejecutado" if action == "approve" else "❌ Rechazado"
        await self._answer(cq_id, footer)
        if chat_id and message_id is not None:
            new_text = f"{original_text}\n\n— {footer}" if original_text else footer
            await self._edit(chat_id=chat_id, message_id=int(message_id), text=new_text)

    async def _answer(self, callback_query_id: str, text: str) -> None:
        try:
            await self._client.post(
                f"{self._base}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text},
            )
        except Exception as exc:  # acknowledgement is best-effort
            log.warning("approval.telegram_poller.answer_failed", error=str(exc))

    async def _edit(self, *, chat_id: str, message_id: int, text: str) -> None:
        try:
            await self._client.post(
                f"{self._base}/editMessageText",
                json={"chat_id": chat_id, "message_id": message_id, "text": text},
            )
        except Exception as exc:  # the card edit is cosmetic; never fail the tap on it
            log.warning("approval.telegram_poller.edit_failed", error=str(exc))


__all__ = ["TelegramCallbackPoller"]
