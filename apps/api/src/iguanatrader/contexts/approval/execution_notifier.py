"""ExecutionNotifier — push execution OUTCOME + close-out updates to the operator.

Slice ``mcp-hitl-approvals`` §6 (Gate E OQ3 = "execution + close-out"), extended
into an execution *firewall*: after the operator approves a proposal over the
channel, they are told the TRUTH of what happened downstream — success AND
failure — never left guessing. Each push is tagged with the trading ``mode`` so
the operator always knows whether it hit the **paper** or the **live** broker.

* ``OrderPlaced``   → "✅ Order sent to broker [PAPER|LIVE] ..." (reached the broker).
* ``OrderRejected`` → "❌ NOT EXECUTED [PAPER|LIVE] ... — <reason>. No order placed."
* ``OrderFilled``   → "🟢 Filled [PAPER|LIVE] ..." (the approved order filled).
* ``TradeClosed``   → "🔚 [PAPER|LIVE] ... closed: +/-<pnl> P&L" (position closed).

The ``OrderRejected`` push is the point of the firewall: before it, a broker
failure (gateway down, auth, budget, NACK) was logged and swallowed, so the
operator approved a card and heard nothing back while nothing executed. Now the
silent-failure path speaks.

Delivery goes to the tenant's enabled ``authorized_senders``. When Hermes is
configured it routes via Hermes (WhatsApp/Telegram); otherwise it falls back to
the same direct Telegram transport the approval cards use — so the pushes reach
the operator even without Hermes. Handlers are **best-effort**: any failure is
logged and swallowed so a notification problem never rolls back execution nor
kills the bus worker.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import structlog

from iguanatrader.contexts.approval.repository import ApprovalRepository

log = structlog.get_logger("iguanatrader.contexts.approval.execution_notifier")

#: Channels Hermes can deliver to on the operator's behalf.
_OPERATOR_CHANNELS: tuple[str, ...] = ("telegram", "whatsapp")

#: Operator-facing text for each ``OrderRejected.reason`` code.
_REJECTION_REASONS: dict[str, str] = {
    "broker_auth": "broker authentication failed",
    "budget": "risk/budget limit exceeded",
    "broker_other": "broker error (e.g. gateway not connected)",
    "gateway_unavailable": "live gateway unavailable",
    "timeout": "broker submit timed out",
}


class _Transport(Protocol):
    """Minimal outbound transport — POST one message to one recipient."""

    async def send(self, *, address: str, body: str) -> str: ...


def _mode_tag(mode: Any) -> str:
    """``[PAPER]`` / ``[LIVE 🔴]`` — an unmistakable paper-vs-real marker.

    Falls back to ``[mode?]`` when the ambient session could not resolve the
    trade/proposal mode, so the operator sees "unknown" rather than a silent
    omission.
    """
    m = str(mode).lower() if mode else ""
    if m == "live":
        return "[LIVE 🔴]"
    if m == "paper":
        return "[PAPER]"
    return "[mode?]"


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
        """Subscribe every outcome handler (idempotent at the bus)."""
        from iguanatrader.contexts.trading.events import (
            OrderFilled,
            OrderPlaced,
            OrderRejected,
            TradeClosed,
        )

        bus.subscribe(OrderPlaced, self.on_order_placed, idempotent=True)
        bus.subscribe(OrderRejected, self.on_order_rejected, idempotent=True)
        bus.subscribe(OrderFilled, self.on_order_filled, idempotent=True)
        bus.subscribe(TradeClosed, self.on_trade_closed, idempotent=True)

    async def on_order_placed(self, event: Any) -> None:
        detail, mode = await self._order_detail(event.order_id)
        tag = _mode_tag(mode)
        what = detail or f"order {event.order_id}"
        body = f"✅ Order sent to broker {tag}: {what}"
        broker_order_id = getattr(event, "broker_order_id", None)
        if broker_order_id:
            body += f" (broker id {broker_order_id})"
        await self._push(event.tenant_id, body)

    async def on_order_rejected(self, event: Any) -> None:
        detail, mode = await self._proposal_detail(event.proposal_id)
        tag = _mode_tag(mode)
        reason = _REJECTION_REASONS.get(event.reason, event.reason)
        what = detail or f"proposal {event.proposal_id}"
        body = f"❌ NOT EXECUTED {tag}: {what} — {reason}. No order placed."
        await self._push(event.tenant_id, body)

    async def on_order_filled(self, event: Any) -> None:
        detail, mode = await self._order_detail(event.order_id)
        tag = _mode_tag(mode)
        what = detail or f"order {event.order_id}"
        body = f"🟢 Filled {tag}: {what}"
        await self._push(event.tenant_id, body)

    async def on_trade_closed(self, event: Any) -> None:
        pnl = event.realised_pnl
        sign = "+" if pnl >= 0 else ""
        mode = await self._trade_mode(getattr(event, "trade_id", None))
        tag = _mode_tag(mode)
        body = (
            f"🔚 {tag} {event.symbol} {event.side} {event.quantity} closed "
            f"({event.exit_reason}): {sign}{pnl} P&L"
        )
        await self._push(event.tenant_id, body)

    async def _order_detail(self, order_id: Any) -> tuple[str, Any]:
        """Return ``("side qty symbol", mode)`` for an order via its trade.

        Degrades to ``("", None)`` when the ambient session is absent or the
        rows are not yet loadable — the caller keeps a minimal message.
        """
        try:
            from iguanatrader.contexts.trading.models import Order, Trade
            from iguanatrader.shared.contextvars import session_var

            session = session_var.get()
            if session is None:
                return "", None
            order = await session.get(Order, order_id)
            if order is None:
                return "", None
            symbol = getattr(order, "symbol", "") or ""
            mode: Any = None
            trade_id = getattr(order, "trade_id", None)
            if trade_id is not None:
                trade = await session.get(Trade, trade_id)
                if trade is not None:
                    mode = getattr(trade, "mode", None)
                    symbol = symbol or (getattr(trade, "symbol", "") or "")
            detail = " ".join(
                str(x)
                for x in (
                    getattr(order, "side", ""),
                    getattr(order, "quantity", ""),
                    symbol,
                )
                if x
            )
            return detail, mode
        except Exception:  # pragma: no cover - degrade to the minimal body
            return "", None

    async def _proposal_detail(self, proposal_id: Any) -> tuple[str, Any]:
        """Return ``("side qty symbol", mode)`` for a proposal; degrade to ``("", None)``."""
        try:
            from iguanatrader.contexts.trading.models import TradeProposal
            from iguanatrader.shared.contextvars import session_var

            session = session_var.get()
            if session is None:
                return "", None
            proposal = await session.get(TradeProposal, proposal_id)
            if proposal is None:
                return "", None
            detail = " ".join(
                str(x)
                for x in (
                    getattr(proposal, "side", ""),
                    getattr(proposal, "quantity", ""),
                    getattr(proposal, "symbol", ""),
                )
                if x
            )
            return detail, getattr(proposal, "mode", None)
        except Exception:  # pragma: no cover - degrade to the minimal body
            return "", None

    async def _trade_mode(self, trade_id: Any) -> Any:
        """Best-effort ``mode`` for a trade id; ``None`` when unresolved."""
        if trade_id is None:
            return None
        try:
            from iguanatrader.contexts.trading.models import Trade
            from iguanatrader.shared.contextvars import session_var

            session = session_var.get()
            if session is None:
                return None
            trade = await session.get(Trade, trade_id)
            return getattr(trade, "mode", None) if trade is not None else None
        except Exception:  # pragma: no cover
            return None

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
    """Construct the notifier from the environment.

    Prefers Hermes (``HERMES_BASE_URL`` + ``HERMES_HMAC_SECRET``); when Hermes
    is not configured, falls back to the same direct Telegram transport the
    approval cards use (``TELEGRAM_BOT_TOKEN``) so the operator still gets the
    execution firewall. Returns ``None`` only when NEITHER is configured — then
    the daemon skips wiring the pushes (no-op, not an error).
    """
    base_url = os.environ.get("HERMES_BASE_URL", "").strip()
    secret = os.environ.get("HERMES_HMAC_SECRET", "").strip()
    if base_url and secret:
        from iguanatrader.shared.channel_dispatch.adapters.hermes import (
            _HttpxHermesTransport,
        )

        transport = _HttpxHermesTransport(base_url=base_url, hmac_secret=secret.encode("utf-8"))
        return ExecutionNotifier(transport=transport)

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if bot_token:
        from iguanatrader.shared.channel_dispatch.adapters.telegram import (
            _HttpxTelegramTransport,
        )

        # Telegram-only fallback: the transport reaches a Telegram chat id, so
        # scope sender lookup to the telegram channel (a whatsapp external_id
        # would not resolve on the Telegram bot API).
        return ExecutionNotifier(
            transport=_HttpxTelegramTransport(bot_token=bot_token),
            channels=("telegram",),
        )

    return None


__all__ = ["ExecutionNotifier", "build_execution_notifier_from_env"]
