"""ExecutionNotifier — push execution + close-out updates to the operator.

Slice ``mcp-hitl-approvals`` §6 (Gate E OQ3 = "execution + close-out").
After the operator approves a proposal over the channel, they are notified
*through to execution*:

* ``OrderFilled``  → "✅ executed ..." (the approved order filled).
* ``TradeClosed``  → "🔚 ... closed: +/-<pnl> P&L" (the position closed).

Both pushes go to the tenant's enabled ``authorized_senders`` via the same
Hermes transport that Hermes uses to reach WhatsApp/Telegram (Hermes routes
on the recipient id). Handlers are **best-effort**: any failure is logged
and swallowed so a notification problem never rolls back execution nor kills
the bus worker.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import structlog

from iguanatrader.contexts.approval.repository import ApprovalRepository

log = structlog.get_logger("iguanatrader.contexts.approval.execution_notifier")

#: Channels Hermes can deliver to on the operator's behalf.
_OPERATOR_CHANNELS: tuple[str, ...] = ("telegram", "whatsapp")


class _Transport(Protocol):
    """Minimal outbound transport — POST one message to one recipient."""

    async def send(self, *, address: str, body: str) -> str: ...


class ExecutionNotifier:
    """Subscribes to trading lifecycle events and pushes operator updates."""

    def __init__(
        self,
        *,
        transport: _Transport,
        channels: tuple[str, ...] = _OPERATOR_CHANNELS,
    ) -> None:
        self._transport = transport
        self._channels = list(channels)

    def register(self, bus: Any) -> None:
        """Subscribe both lifecycle handlers (idempotent at the bus)."""
        from iguanatrader.contexts.trading.events import OrderFilled, TradeClosed

        bus.subscribe(OrderFilled, self.on_order_filled, idempotent=True)
        bus.subscribe(TradeClosed, self.on_trade_closed, idempotent=True)

    async def on_order_filled(self, event: Any) -> None:
        body = await self._order_filled_body(event)
        await self._push(event.tenant_id, body)

    async def on_trade_closed(self, event: Any) -> None:
        pnl = event.realised_pnl
        sign = "+" if pnl >= 0 else ""
        body = (
            f"🔚 {event.symbol} {event.side} {event.quantity} closed "
            f"({event.exit_reason}): {sign}{pnl} P&L"
        )
        await self._push(event.tenant_id, body)

    async def _order_filled_body(self, event: Any) -> str:
        """Enrich the execution message with the order's symbol/side/qty when
        the ambient session can load it; otherwise a minimal confirmation."""
        try:
            from iguanatrader.contexts.trading.models import Order
            from iguanatrader.shared.contextvars import session_var

            session = session_var.get()
            if session is not None:
                order = await session.get(Order, event.order_id)
                if order is not None:
                    detail = " ".join(
                        str(x)
                        for x in (
                            getattr(order, "side", ""),
                            getattr(order, "quantity", ""),
                            getattr(order, "symbol", ""),
                        )
                        if x
                    )
                    if detail:
                        return f"✅ Executed {detail} (order {event.order_id})"
        except Exception:  # pragma: no cover - degrade to the minimal body
            pass
        return f"✅ Order {event.order_id} executed."

    async def _push(self, tenant_id: Any, body: str) -> None:
        try:
            repo = ApprovalRepository()
            senders = await repo.list_enabled_senders(
                tenant_id=tenant_id,
                channels=self._channels,
            )
            for s in senders:
                try:
                    await self._transport.send(address=s.external_id, body=body)
                except Exception as exc:
                    log.warning(
                        "approval.execution_notify.send_failed",
                        address=s.external_id,
                        error=str(exc),
                    )
        except Exception as exc:  # never escape into the bus worker
            log.warning(
                "approval.execution_notify.failed",
                tenant_id=str(tenant_id),
                error=str(exc),
            )


def build_execution_notifier_from_env() -> ExecutionNotifier | None:
    """Construct the notifier from ``HERMES_BASE_URL`` + ``HERMES_HMAC_SECRET``.

    Returns ``None`` when Hermes is not configured so the daemon simply
    skips wiring the operator pushes (no-op, not an error).
    """
    base_url = os.environ.get("HERMES_BASE_URL", "").strip()
    secret = os.environ.get("HERMES_HMAC_SECRET", "").strip()
    if not base_url or not secret:
        return None
    from iguanatrader.shared.channel_dispatch.adapters.hermes import (
        _HttpxHermesTransport,
    )

    transport = _HttpxHermesTransport(base_url=base_url, hmac_secret=secret.encode("utf-8"))
    return ExecutionNotifier(transport=transport)


__all__ = ["ExecutionNotifier", "build_execution_notifier_from_env"]
