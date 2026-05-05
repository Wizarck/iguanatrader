"""Portfolio route stubs — 501 Problem until slice T4 lands the bodies.

Per design D6 + slice-5 D9 precedent. Mirror of
:mod:`iguanatrader.api.routes.trades` shape.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from iguanatrader.api.deps import get_current_user
from iguanatrader.api.dtos.trades import (
    EquitySnapshotOut,
    PortfolioSummaryOut,
)
from iguanatrader.persistence import User
from iguanatrader.shared.errors import NotImplementedFeatureError

log = structlog.get_logger("iguanatrader.api.routes.portfolio")

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _stub(method: str, path: str) -> NotImplementedFeatureError:
    """Build the canonical 501 raise for a trading-route stub."""
    log.info(
        "trading.routes.stub_invoked",
        method=method,
        path=path,
    )
    return NotImplementedFeatureError(
        detail=(f"{method} /api/v1{path} will be wired in slice T4 (trading-routes-and-daemon)."),
    )


@router.get("", response_model=PortfolioSummaryOut)
async def get_portfolio(
    user: User = Depends(get_current_user),
) -> PortfolioSummaryOut:
    """Return a snapshot of the current portfolio. (T4 fills.)"""
    raise _stub("GET", "/portfolio")


@router.get("/positions")
async def list_positions(
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """List open positions. (T4 fills the response_model + body.)"""
    raise _stub("GET", "/portfolio/positions")


@router.get("/equity", response_model=EquitySnapshotOut)
async def latest_equity(
    user: User = Depends(get_current_user),
) -> EquitySnapshotOut:
    """Return the latest equity snapshot. (T4 fills.)"""
    raise _stub("GET", "/portfolio/equity")


__all__ = ["router"]
