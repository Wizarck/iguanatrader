"""Portfolio read endpoints (slice trading-routes-portfolio-strategies-bodies).

Three GET endpoints powered by :class:`TradeRepository`,
:class:`OrderRepository`, :class:`EquitySnapshotRepository`, and
:class:`FillRepository`. Tenant scoping is automatic via the slice-3
``tenant_listener``.

The ``response_model=...`` declarations are intentional — they make
the canonical response shape visible in ``/openapi.json`` so the
slice-5 typegen pipeline emits the matching TypeScript interfaces in
``packages/shared-types/src/index.ts``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.trades import (
    EquitySnapshotListOut,
    EquitySnapshotOut,
    OrderOut,
    PortfolioSummaryOut,
    PositionListOut,
    PositionOut,
    TradeOut,
)
from iguanatrader.contexts.trading.models import EquitySnapshot, Trade
from iguanatrader.contexts.trading.repository import (
    EquitySnapshotRepository,
    FillRepository,
    OrderRepository,
    TradeRepository,
)
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var
from iguanatrader.shared.errors import NotFoundError

log = structlog.get_logger("iguanatrader.api.routes.portfolio")

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _synthesise_empty_equity(tenant_id: UUID) -> EquitySnapshotOut:
    """Build a zero-valued :class:`EquitySnapshotOut` for an empty tenant.

    ``GET /portfolio`` returns this when the tenant has no real snapshot
    yet so the dashboard can render "Sin movimiento aún" without
    special-casing 404. The ``snapshot_kind="empty"`` discriminator is
    a DTO-only sentinel — it is NOT a valid value for the DB-level
    CHECK constraint (``'event' | 'minute' | 'daily'``) and the row is
    never persisted.
    """
    return EquitySnapshotOut(
        id=uuid4(),
        tenant_id=tenant_id,
        mode="paper",
        account_equity=Decimal("0"),
        cash_balance=Decimal("0"),
        realized_pnl_today=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        currency="USD",
        snapshot_kind="empty",
        created_at=datetime.now(UTC),
    )


async def _compute_avg_entry_price(
    fill_repo: FillRepository,
    trade_id: UUID,
) -> Decimal | None:
    """Return ``sum(fill_price * quantity_filled) / sum(quantity_filled)``.

    Returns ``None`` when the trade has no fills recorded yet (the
    proposal was approved + the order submitted but the broker has not
    reported execution). Frontend renders ``—`` for null values.
    """
    fills = await fill_repo.list_for_trade(trade_id)
    if not fills:
        return None
    total_qty = Decimal("0")
    weighted_sum = Decimal("0")
    for fill in fills:
        qty = Decimal(fill.quantity_filled)
        price = Decimal(fill.fill_price)
        total_qty += qty
        weighted_sum += qty * price
    if total_qty == Decimal("0"):
        return None
    return weighted_sum / total_qty


def _trade_to_position(
    trade: Trade,
    avg_entry_price: Decimal | None,
) -> PositionOut:
    """Project a :class:`Trade` row + computed avg-entry into a DTO row.

    ``last_price`` and ``unrealized_pnl`` are intentionally null in v1.
    The market-data hook that populates them is owned by the follow-up
    slice ``market-data-snapshot-port``.
    """
    return PositionOut(
        trade_id=trade.id,
        symbol=trade.symbol,
        side=trade.side,
        quantity=Decimal(trade.quantity),
        avg_entry_price=avg_entry_price,
        last_price=None,
        unrealized_pnl=None,
        opened_at=trade.opened_at,
    )


@router.get("", response_model=PortfolioSummaryOut)
async def get_portfolio(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortfolioSummaryOut:
    """Return a snapshot of the current portfolio.

    Returns the latest :class:`EquitySnapshot` for the tenant (or a
    synthesised zero snapshot with ``snapshot_kind="empty"`` when the
    tenant has none yet), plus the open trades and open orders. The
    synthesised-empty branch is deliberate so the dashboard can render
    a stable shape from first boot without special-casing 404. The
    sibling ``GET /portfolio/equity`` keeps the 404 contract for
    callers that specifically want history.
    """
    session_var.set(db)

    equity_repo = EquitySnapshotRepository()
    trade_repo = TradeRepository()
    order_repo = OrderRepository()

    latest_equity: EquitySnapshot | None = await equity_repo.get_latest_for_tenant()
    day_open: EquitySnapshot | None = await equity_repo.get_first_snapshot_today_for_tenant()
    open_trades = await trade_repo.list_open_for_tenant()
    open_orders = await order_repo.list_open_for_tenant()

    if latest_equity is None:
        equity_out = _synthesise_empty_equity(user.tenant_id)
    else:
        equity_out = EquitySnapshotOut.model_validate(latest_equity)

    day_pnl_abs: Decimal | None = None
    day_pnl_pct: Decimal | None = None
    if latest_equity is not None and day_open is not None and day_open.account_equity > 0:
        day_pnl_abs = latest_equity.account_equity - day_open.account_equity
        day_pnl_pct = day_pnl_abs / day_open.account_equity

    log.info(
        "portfolio.summary.fetched",
        tenant_id=str(user.tenant_id),
        open_trades=len(open_trades),
        open_orders=len(open_orders),
        equity_synthesised=latest_equity is None,
        day_pnl_computed=day_pnl_abs is not None,
    )

    return PortfolioSummaryOut(
        equity=equity_out,
        open_trades=[TradeOut.model_validate(t) for t in open_trades],
        open_orders=[OrderOut.model_validate(o) for o in open_orders],
        day_pnl_abs=day_pnl_abs,
        day_pnl_pct=day_pnl_pct,
    )


@router.get("/positions", response_model=PositionListOut)
async def list_positions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PositionListOut:
    """List derived positions — one row per open trade.

    A "position" is computed from each open :class:`Trade` plus the
    cumulative fills attached to its order(s):

    * ``avg_entry_price`` = ``sum(fill_price * quantity_filled) /
      sum(quantity_filled)`` across fills, or ``None`` if no fills yet.
    * ``last_price`` and ``unrealized_pnl`` are intentionally ``None``
      in v1 (the market-data hook is a follow-up slice).

    Sorted ``opened_at DESC``. Empty list when no open trades.
    """
    session_var.set(db)
    trade_repo = TradeRepository()
    fill_repo = FillRepository()

    open_trades = await trade_repo.list_open_for_tenant()
    positions: list[PositionOut] = []
    for trade in open_trades:
        avg = await _compute_avg_entry_price(fill_repo, trade.id)
        positions.append(_trade_to_position(trade, avg))

    log.info(
        "portfolio.positions.fetched",
        tenant_id=str(user.tenant_id),
        position_count=len(positions),
    )

    return PositionListOut(items=positions, total=len(positions))


@router.get("/equity", response_model=EquitySnapshotOut)
async def latest_equity(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EquitySnapshotOut:
    """Return the latest equity snapshot for the tenant.

    Returns 404 when the tenant has zero snapshots — distinct from the
    ``GET /portfolio`` synthesised-empty branch because callers of
    ``/equity`` specifically want history. The frontend renders the
    404 inline as "Sin snapshots aún".
    """
    session_var.set(db)
    repo = EquitySnapshotRepository()
    snapshot = await repo.get_latest_for_tenant()
    if snapshot is None:
        log.info(
            "portfolio.equity.fetched",
            tenant_id=str(user.tenant_id),
            outcome="not_found",
        )
        raise NotFoundError(
            detail=f"No equity snapshots recorded for tenant {user.tenant_id}.",
        )
    log.info(
        "portfolio.equity.fetched",
        tenant_id=str(user.tenant_id),
        outcome="hit",
        snapshot_id=str(snapshot.id),
    )
    return EquitySnapshotOut.model_validate(snapshot)


@router.get("/equity/series", response_model=EquitySnapshotListOut)
async def equity_series(
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EquitySnapshotListOut:
    """Return equity snapshots for the last ``days`` days (ordered ASC).

    ``days`` defaults to 30 (sparkline horizon) and is clamped 1..365.
    Returns ``items=[]`` (NOT 404) when no snapshots fall in the window —
    the dashboard sparkline renders "Sin datos aún" inline.
    """
    session_var.set(db)
    repo = EquitySnapshotRepository()
    snapshots = await repo.list_for_tenant_window(days)
    items = [EquitySnapshotOut.model_validate(s) for s in snapshots]
    log.info(
        "portfolio.equity_series.fetched",
        tenant_id=str(user.tenant_id),
        days=days,
        count=len(items),
    )
    return EquitySnapshotListOut(items=items, total=len(items), next_cursor=None)


__all__ = ["router"]
