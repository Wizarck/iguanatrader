"""Strategies route stubs — 501 Problem until slice T4 lands the bodies.

Per design D6. Endpoints cover FR1 (list), FR2 (enable/disable), FR3
(per-symbol params), FR4 (hot-reload tracked via the version column).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from iguanatrader.api.deps import get_current_user
from iguanatrader.api.dtos.trades import (
    StrategyConfigIn,
    StrategyConfigListOut,
    StrategyConfigOut,
)
from iguanatrader.persistence import User
from iguanatrader.shared.errors import NotImplementedFeatureError

log = structlog.get_logger("iguanatrader.api.routes.strategies")

router = APIRouter(prefix="/strategies", tags=["strategies"])


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


@router.get("", response_model=StrategyConfigListOut)
async def list_strategies(
    user: User = Depends(get_current_user),
) -> StrategyConfigListOut:
    """List strategy configurations for the authenticated tenant (FR1)."""
    raise _stub("GET", "/strategies")


@router.get("/{symbol}", response_model=StrategyConfigOut)
async def get_strategy(
    symbol: str,
    user: User = Depends(get_current_user),
) -> StrategyConfigOut:
    """Fetch the strategy config for ``symbol`` (FR3)."""
    raise _stub("GET", f"/strategies/{symbol}")


@router.put("/{symbol}", response_model=StrategyConfigOut)
async def upsert_strategy(
    symbol: str,
    body: StrategyConfigIn,
    user: User = Depends(get_current_user),
) -> StrategyConfigOut:
    """Upsert strategy config for ``symbol`` (FR2 + FR3)."""
    _ = body  # T4 fills — currently the stub raises before consuming the body.
    raise _stub("PUT", f"/strategies/{symbol}")


@router.delete("/{symbol}")
async def disable_strategy(
    symbol: str,
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Disable the strategy for ``symbol`` (FR2)."""
    raise _stub("DELETE", f"/strategies/{symbol}")


__all__ = ["router"]
