"""Cost / observability HTTP routes — discovered + mounted at ``/api/v1/costs/*``.

Slice O1 endpoints (per FR42 + design.md "Routes + SSE + DTOs"):

- ``GET /costs/summary`` — current calendar-month totals (`CostSummaryDTO`).
- ``GET /costs/by-provider`` — current calendar-month breakdown
  (`CostByProviderDTO`).
- ``GET /costs/per-trade`` — current calendar-month cost-per-trade ratio
  (`CostPerTradeDTO`); ``closed_trades_count`` is zero until slice T1
  lands the trading bounded context.

All endpoints require an authenticated user (per the project's hard-rule
default — :func:`iguanatrader.api.deps.get_current_user`); the slice-3
listener auto-filters ``api_cost_events`` to the bound tenant. Errors
flow through the global RFC 7807 handler chain (slice 5).

The router is auto-discovered by
:func:`iguanatrader.api.routes.register_routers` — no edit to
``app.py`` per the slice-5 anti-collision contract.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.costs import (
    CostByProviderDTO,
    CostPerTradeDTO,
    CostSummaryDTO,
    PerProviderBreakdown,
)
from iguanatrader.contexts.observability.budget import month_window
from iguanatrader.contexts.observability.models import ApiCostEvent
from iguanatrader.persistence import User

log = structlog.get_logger("iguanatrader.api.routes.costs")

router = APIRouter(prefix="/costs", tags=["costs"])


async def _summary_aggregate(
    session: AsyncSession,
    tenant_id: UUID,
    start: datetime,
    end: datetime,
) -> tuple[Decimal, int, int]:
    """Return ``(total_cost_usd, total_calls, cached_calls)`` for ``[start, end)``.

    Cached counting is done client-side (Python loop) for portability:
    SQLite Booleans are 0/1 ints so a direct ``SUM(cached)`` would work,
    but Postgres exposes Boolean as an explicit type that needs an
    ``::int`` cast to sum. The two-pass approach is uniform.
    """
    stmt = (
        select(ApiCostEvent.cost_usd, ApiCostEvent.cached)
        .where(ApiCostEvent.tenant_id == tenant_id)
        .where(ApiCostEvent.created_at >= start)
        .where(ApiCostEvent.created_at < end)
    )
    result = await session.execute(stmt)
    rows = list(result.all())

    total_cost = Decimal("0")
    cached_calls = 0
    for cost_raw, cached_flag in rows:
        cost_value = cost_raw if isinstance(cost_raw, Decimal) else Decimal(str(cost_raw))
        total_cost += cost_value
        if cached_flag:
            cached_calls += 1
    return total_cost, len(rows), cached_calls


@router.get("/summary", response_model=CostSummaryDTO)
async def get_cost_summary(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> CostSummaryDTO:
    """Current-month totals for the authenticated tenant."""
    start, end = month_window()
    total_cost, total_calls, cached_calls = await _summary_aggregate(
        session, user.tenant_id, start, end
    )
    log.info(
        "observability.cost.summary_requested",
        tenant_id=str(user.tenant_id),
        total_cost_usd=str(total_cost),
        total_calls=total_calls,
    )
    return CostSummaryDTO(
        tenant_id=user.tenant_id,
        period_start=start,
        period_end=end,
        total_cost_usd=total_cost,
        total_calls=total_calls,
        cached_calls=cached_calls,
    )


@router.get("/by-provider", response_model=CostByProviderDTO)
async def get_cost_by_provider(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> CostByProviderDTO:
    """Current-month per-provider breakdown for the authenticated tenant."""
    start, end = month_window()
    stmt = (
        select(ApiCostEvent.provider, ApiCostEvent.cost_usd)
        .where(ApiCostEvent.tenant_id == user.tenant_id)
        .where(ApiCostEvent.created_at >= start)
        .where(ApiCostEvent.created_at < end)
    )
    result = await session.execute(stmt)

    cost_by_provider: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    count_by_provider: dict[str, int] = defaultdict(int)
    for provider, cost_usd in result.all():
        cost_value = cost_usd if isinstance(cost_usd, Decimal) else Decimal(str(cost_usd))
        cost_by_provider[provider] += cost_value
        count_by_provider[provider] += 1

    breakdown = [
        PerProviderBreakdown(
            provider=provider,
            cost_usd=cost,
            call_count=count_by_provider[provider],
        )
        for provider, cost in sorted(cost_by_provider.items())
    ]
    return CostByProviderDTO(
        tenant_id=user.tenant_id,
        period_start=start,
        period_end=end,
        breakdown=breakdown,
    )


@router.get("/per-trade", response_model=CostPerTradeDTO)
async def get_cost_per_trade(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> CostPerTradeDTO:
    """Current-month cost-per-trade ratio (FR42).

    Until slice T1 lands the trading bounded context,
    ``closed_trades_count`` is zero and ``cost_per_trade_usd`` is
    ``None``. Slice T1 wires the trades-counting query.
    """
    start, end = month_window()
    total_cost, _total_calls, _cached_calls = await _summary_aggregate(
        session, user.tenant_id, start, end
    )

    closed_trades_count = 0  # slice T1 plants the real query
    if closed_trades_count > 0:
        cost_per_trade: Decimal | None = total_cost / Decimal(closed_trades_count)
    else:
        cost_per_trade = None

    return CostPerTradeDTO(
        tenant_id=user.tenant_id,
        period_start=start,
        period_end=end,
        total_llm_cost_usd=total_cost,
        closed_trades_count=closed_trades_count,
        cost_per_trade_usd=cost_per_trade,
    )


__all__ = [
    "router",
]
