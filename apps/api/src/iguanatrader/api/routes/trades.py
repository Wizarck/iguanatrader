"""Trades route stubs — 501 Problem until slice T4 lands the bodies.

Each handler raises :class:`NotImplementedFeatureError` (slice 5 D9
precedent for stub-route status canonicalisation per design D6); the
slice-5 global exception handler renders RFC 7807 with type
``urn:iguanatrader:error:not-implemented`` + HTTP 501.

The ``response_model=...`` declarations are intentional — they make the
canonical response shape visible in ``/openapi.json`` so the slice-5
typegen pipeline emits the matching TypeScript interfaces in
``packages/shared-types/src/index.ts``. Slice T4 replaces the bodies
without touching the route signatures.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends

from iguanatrader.api.deps import get_current_user
from iguanatrader.api.dtos.trades import (
    FillListOut,
    TradeListOut,
    TradeOut,
)
from iguanatrader.persistence import User
from iguanatrader.shared.errors import NotImplementedFeatureError

log = structlog.get_logger("iguanatrader.api.routes.trades")

router = APIRouter(prefix="/trades", tags=["trades"])


def _stub(method: str, path: str) -> NotImplementedFeatureError:
    """Build the canonical 501 raise for a trading-route stub."""
    log.info(
        "trading.routes.stub_invoked",
        method=method,
        path=path,
    )
    return NotImplementedFeatureError(
        detail=(
            f"{method} /api/v1{path} will be wired in slice T4 "
            "(trading-routes-and-daemon)."
        ),
    )


@router.get("", response_model=TradeListOut)
async def list_trades(
    user: User = Depends(get_current_user),
) -> TradeListOut:
    """List trades for the authenticated tenant. (T4 fills.)"""
    raise _stub("GET", "/trades")


@router.get("/{trade_id}", response_model=TradeOut)
async def get_trade(
    trade_id: UUID,
    user: User = Depends(get_current_user),
) -> TradeOut:
    """Fetch a single trade by id. (T4 fills.)"""
    raise _stub("GET", f"/trades/{trade_id}")


@router.get("/{trade_id}/fills", response_model=FillListOut)
async def list_trade_fills(
    trade_id: UUID,
    user: User = Depends(get_current_user),
) -> FillListOut:
    """List fills for a given trade. (T4 fills.)"""
    raise _stub("GET", f"/trades/{trade_id}/fills")


__all__ = ["router"]
