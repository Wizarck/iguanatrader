"""Strategies CRUD endpoints (slice trading-routes-portfolio-strategies-bodies).

Four endpoints powered by :class:`StrategyConfigRepository`. Tenant
scoping is automatic via the slice-3 ``tenant_listener``. Per design
D6: FR1 (list), FR2 (enable/disable via PUT + DELETE soft-disable),
FR3 (per-symbol params), FR4 (hot-reload tracked via the ``version``
column bumped by the ``StrategyConfig.before_update`` hook).

The ``response_model=...`` declarations are intentional — they make
the canonical response shape visible in ``/openapi.json`` so the
slice-5 typegen pipeline emits the matching TypeScript interfaces in
``packages/shared-types/src/index.ts``.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.trades import (
    StrategyConfigIn,
    StrategyConfigListOut,
    StrategyConfigOut,
)
from iguanatrader.contexts.trading.repository import StrategyConfigRepository
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var
from iguanatrader.shared.errors import NotFoundError

log = structlog.get_logger("iguanatrader.api.routes.strategies")

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=StrategyConfigListOut)
async def list_strategies(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyConfigListOut:
    """List strategy configurations for the authenticated tenant (FR1).

    Ordered ``(symbol ASC, strategy_kind ASC)``. Tenant filter is
    automatic via the slice-3 ``tenant_listener``.
    """
    session_var.set(db)
    repo = StrategyConfigRepository()
    rows = await repo.list_for_tenant()
    log.info(
        "strategies.list.fetched",
        tenant_id=str(user.tenant_id),
        count=len(rows),
    )
    return StrategyConfigListOut(
        items=[StrategyConfigOut.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get("/{symbol}", response_model=StrategyConfigOut)
async def get_strategy(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyConfigOut:
    """Fetch the strategy config for ``symbol`` (FR3).

    Returns the first (oldest-``created_at``) enabled config for the
    symbol, or 404 if none. The backend allows multiple strategy_kinds
    per symbol (composite UNIQUE is ``(tenant_id, strategy_kind,
    symbol)``); v1 GET-by-symbol picks the oldest enabled row by
    convention. Multi-kind-per-symbol UI is owned by a v1.5 follow-up
    slice (``strategies-multi-kind-ui``).
    """
    session_var.set(db)
    repo = StrategyConfigRepository()
    row = await repo.get_first_enabled_by_symbol(symbol)
    if row is None:
        raise NotFoundError(detail=f"No enabled strategy config for symbol {symbol!r}.")
    log.info(
        "strategies.get.fetched",
        tenant_id=str(user.tenant_id),
        symbol=symbol,
        strategy_config_id=str(row.id),
    )
    return StrategyConfigOut.model_validate(row)


@router.put("/{symbol}", response_model=StrategyConfigOut)
async def upsert_strategy(
    symbol: str,
    body: StrategyConfigIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyConfigOut:
    """Upsert strategy config for ``symbol`` (FR2 + FR3).

    Delegates to :meth:`StrategyConfigRepository.upsert`. On UPDATE the
    ``StrategyConfig.before_update`` hook bumps ``version`` and emits
    ``trading.config.changed``. The repo's INSERT/UPDATE distinction is
    keyed on ``(tenant_id, strategy_kind, symbol)``.
    """
    session_var.set(db)
    repo = StrategyConfigRepository()
    row = await repo.upsert(
        symbol=symbol,
        strategy_kind=body.strategy_kind,
        params=body.params,
        enabled=body.enabled,
    )
    await db.commit()
    await db.refresh(row)
    log.info(
        "strategies.upsert.applied",
        tenant_id=str(user.tenant_id),
        symbol=symbol,
        strategy_kind=body.strategy_kind,
        strategy_config_id=str(row.id),
        new_version=row.version,
    )
    return StrategyConfigOut.model_validate(row)


@router.delete("/{symbol}")
async def disable_strategy(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Soft-disable every strategy config for ``symbol`` (FR2).

    Sets ``enabled=False`` on each row the caller's tenant owns for
    that symbol — preserves audit history (no DB row removal). Returns
    404 when no rows exist for the symbol. Per-row UPDATE via the ORM
    so the slice-3 ``tenant_listener`` filters the preceding SELECT
    and the ``before_update`` hook bumps ``version``.
    """
    session_var.set(db)
    repo = StrategyConfigRepository()
    rows = await repo.list_all_by_symbol(symbol)
    if not rows:
        raise NotFoundError(detail=f"No strategy config rows for symbol {symbol!r}.")
    touched = await repo.disable_all_by_symbol(symbol)
    await db.commit()
    log.info(
        "strategies.disabled",
        tenant_id=str(user.tenant_id),
        symbol=symbol,
        rows_seen=len(rows),
        rows_touched=touched,
    )
    return {"status": "disabled", "symbol": symbol}


__all__ = ["router"]
