"""Pure renderer for a human-clear trade-proposal approval card.

Turns a persisted ``TradeProposal`` into an unambiguous Spanish prompt
that states *what* action to take (buy / go long vs. sell short), the
entry, the take-profit target and the protective stop — so the operator
reading the Telegram / WhatsApp message knows exactly **when to buy and
when to sell**. Side-aware: a long says "vender en objetivo / vender si
toca stop"; a short says "recomprar …".

Kept pure (no I/O, no session) so the channel adapters can render it and
unit tests can assert the wording without a broker or a database.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def _pct(*, frm: Decimal, to: Decimal) -> str:
    """Signed percentage move from ``frm`` to ``to`` (1 decimal)."""
    if frm == 0:
        return "n/d"
    delta = (to - frm) / frm * Decimal("100")
    return f"{delta:+.1f}%"


def render_proposal_card(
    *,
    request_id: UUID,
    proposal_id: UUID,
    symbol: str,
    side: str,
    quantity: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
    target_price: Decimal | None,
    expires_at: datetime,
    reasoning: dict[str, Any] | None = None,
) -> str:
    """Render the side-aware approval card. ``side`` is ``"buy"``/``"sell"``."""
    is_long = side == "buy"
    reasoning = reasoning or {}
    lookback = reasoning.get("lookback")
    level = reasoning.get("breakout_level")

    if is_long:
        head = f"🟢 COMPRAR (LARGO) {symbol}"
        motivo = (
            f"ruptura del MÁXIMO de {lookback} días ({level})"
            if lookback and level
            else "ruptura alcista del canal Donchian"
        )
        target_label = "Vender en objetivo"
        stop_label = "Vender si toca stop"
    else:
        head = f"🔴 VENDER EN CORTO {symbol}"
        motivo = (
            f"ruptura del MÍNIMO de {lookback} días ({level})"
            if lookback and level
            else "ruptura bajista del canal Donchian"
        )
        target_label = "Recomprar en objetivo"
        stop_label = "Recomprar si toca stop"

    lines = [
        head,
        f"Cantidad: {quantity}",
        f"Entrada ~ {entry_price}  ·  {motivo}",
    ]
    if target_price is not None:
        lines.append(
            f"🎯 {target_label}: {target_price}  ({_pct(frm=entry_price, to=target_price)})"
        )
    lines.append(f"🛑 {stop_label}: {stop_price}  ({_pct(frm=entry_price, to=stop_price)})")
    lines.append("")
    lines.append(f"Aprobar: /approve {request_id}   ·   Rechazar: /reject {request_id}")
    lines.append(f"Propuesta: {proposal_id}  ·  expira: {expires_at.isoformat()}")
    return "\n".join(lines)


def render_exit_card(
    *,
    request_id: UUID,
    trade_id: UUID,
    symbol: str,
    side: str,
    quantity: Decimal,
    expires_at: datetime,
    rationale: str | None = None,
    confidence: Decimal | None = None,
    unrealized_pnl: Decimal | None = None,
) -> str:
    """Render the WS-5 urgent-exit approval card (Spanish, side-aware).

    ``side`` is the OPEN position's side (``"buy"`` = long, ``"sell"`` =
    short); approving CLOSES it (a long closes by selling, a short by
    recompra). Kept pure so unit tests assert the wording without I/O.
    """
    is_long = side == "buy"
    accion = "VENDER" if is_long else "RECOMPRAR"
    head = f"🚨 {accion} URGENTE {symbol} (CERRAR {'LARGO' if is_long else 'CORTO'})"
    lines = [
        head,
        f"Cantidad: {quantity}",
    ]
    if unrealized_pnl is not None:
        lines.append(f"P&L no realizado: {unrealized_pnl}")
    if confidence is not None:
        lines.append(f"Confianza del análisis: {confidence}")
    if rationale:
        lines.append(f"Motivo: {rationale}")
    lines.append("")
    lines.append(f"Aprobar cierre: /approve {request_id}   ·   Mantener: /reject {request_id}")
    lines.append(f"Posición: {trade_id}  ·  expira: {expires_at.isoformat()}")
    return "\n".join(lines)


__all__ = ["render_exit_card", "render_proposal_card"]
