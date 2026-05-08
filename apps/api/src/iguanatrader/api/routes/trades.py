"""Trades read endpoints (slice trades-read-endpoints).

Three GET endpoints powered by :class:`TradeRepository` +
:class:`FillRepository`. Tenant scoping is automatic via the slice-3
``tenant_listener``. Pagination cursor returns ``None`` in v1; v2 SaaS
slice adds it once trade volume warrants.

The ``response_model=...`` declarations are intentional — they make
the canonical response shape visible in ``/openapi.json`` so the
slice-5 typegen pipeline emits the matching TypeScript interfaces in
``packages/shared-types/src/index.ts``.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.trades import (
    FillListOut,
    FillOut,
    TradeListOut,
    TradeOut,
)
from iguanatrader.contexts.trading.repository import (
    FillRepository,
    TradeRepository,
)
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var
from iguanatrader.shared.errors import NotFoundError

log = structlog.get_logger("iguanatrader.api.routes.trades")

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=TradeListOut)
async def list_trades(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TradeListOut:
    """List trades for the authenticated tenant (slice trades-read-endpoints)."""
    log.info("api.trades.list", tenant_id=str(user.tenant_id))
    session_var.set(db)
    repo = TradeRepository()
    rows = await repo.list_for_tenant()
    return TradeListOut(
        items=[TradeOut.model_validate(r) for r in rows],
        total=len(rows),
        next_cursor=None,
    )


@router.get("/{trade_id}", response_model=TradeOut)
async def get_trade(
    trade_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TradeOut:
    """Fetch a single trade by id (slice trades-read-endpoints)."""
    log.info("api.trades.get", trade_id=str(trade_id))
    session_var.set(db)
    repo = TradeRepository()
    row = await repo.get_by_id(trade_id)
    if row is None:
        raise NotFoundError(detail=f"Trade {trade_id} not found.")
    return TradeOut.model_validate(row)


@router.get("/{trade_id}/fills", response_model=FillListOut)
async def list_trade_fills(
    trade_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FillListOut:
    """List fills for a given trade (slice trades-read-endpoints).

    A trade with no fills yet returns an empty list (NOT 404) — the
    proposal could be approved + the order submitted but no broker
    execution yet. Empty list is the canonical in-flight response.
    """
    log.info("api.trades.fills", trade_id=str(trade_id))
    session_var.set(db)
    repo = FillRepository()
    rows = await repo.list_for_trade(trade_id)
    return FillListOut(
        items=[FillOut.model_validate(r) for r in rows],
        total=len(rows),
        next_cursor=None,
    )


__all__ = ["router"]
