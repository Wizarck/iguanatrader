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
from iguanatrader.contexts.trading.market_data import MarketDataNotAvailableError
from iguanatrader.contexts.trading.market_data.db import DBMarketDataAdapter
from iguanatrader.contexts.trading.models import EquitySnapshot, Trade
from iguanatrader.contexts.trading.repository import (
    EquitySnapshotRepository,
    FillRepository,
    OpenPositionRow,
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


async def _fetch_last_price(
    adapter: DBMarketDataAdapter,
    symbol: str,
) -> Decimal | None:
    """Return last 1d-bar close for ``symbol``, or ``None`` if no bars exist."""
    try:
        bars = await adapter.get_bars(symbol=symbol, timeframe="1d", lookback_bars=1)
    except MarketDataNotAvailableError:
        return None
    if not bars.bars:
        return None
    return Decimal(bars.bars[-1].close)


def _compute_unrealized_pnl(
    *,
    trade: Trade,
    avg_entry: Decimal | None,
    last_price: Decimal | None,
) -> Decimal | None:
    """Compute mark-to-market unrealized P&L for an open trade.

    Returns ``None`` when either ``avg_entry`` or ``last_price`` is missing
    (frontend renders "—" for the position row). Sign convention:
    ``buy`` side → ``(last - entry) * qty``; ``sell`` side → ``(entry - last) * qty``.
    """
    if avg_entry is None or last_price is None:
        return None
    # WHY: longs profit when price rises; shorts profit when price falls.
    delta = last_price - avg_entry if trade.side == "buy" else avg_entry - last_price
    return delta * Decimal(trade.quantity)


def _position_from_row(
    row: OpenPositionRow,
    fill_avg_entry: Decimal | None,
    last_price: Decimal | None,
) -> PositionOut:
    """Project an :class:`OpenPositionRow` + computed fields into a DTO row.

    Source preference reconciles the two truths an open position can have —
    locally-derived (fills + market data) vs broker-reconciled marks
    (``trade.avg_entry_price`` / ``trade.unrealized_pnl``, stamped by the
    daemon's IBKR reconcile, migration 0040):

    * ``avg_entry_price`` — fill-weighted average when fills exist, else the
      broker's reconciled avgCost. Keeps continuity for normally-filled trades
      while recovering positions whose fills predate the reqExecutions window.
    * ``unrealized_pnl`` — mark-to-market computed from the RESOLVED avg vs
      ``last_price``, so the figure is always self-consistent with the avg +
      last columns the row displays. Falls back to the broker's own uPnL only
      when avg or last is unavailable (e.g. no market-data bars yet). The
      broker's paper-account uPnL is frequently ``0`` without a live
      market-data subscription, so computing it ourselves is both more
      informative and coherent with the displayed prices.

    The strategy / planned-entry / stop / target come straight off the joined
    proposal + config.
    """
    trade = row.trade
    broker_avg = Decimal(trade.avg_entry_price) if trade.avg_entry_price is not None else None
    broker_unrealized = Decimal(trade.unrealized_pnl) if trade.unrealized_pnl is not None else None
    avg_entry_price = fill_avg_entry if fill_avg_entry is not None else broker_avg
    computed_unrealized = _compute_unrealized_pnl(
        trade=trade, avg_entry=avg_entry_price, last_price=last_price
    )
    unrealized_pnl = computed_unrealized if computed_unrealized is not None else broker_unrealized
    return PositionOut(
        trade_id=trade.id,
        symbol=trade.symbol,
        side=trade.side,
        quantity=Decimal(trade.quantity),
        avg_entry_price=avg_entry_price,
        last_price=last_price,
        unrealized_pnl=unrealized_pnl,
        marks_updated_at=trade.marks_updated_at,
        opened_at=trade.opened_at,
        strategy_kind=row.strategy_kind,
        entry_price_indicative=(
            Decimal(row.entry_price_indicative) if row.entry_price_indicative is not None else None
        ),
        stop_price=Decimal(row.stop_price) if row.stop_price is not None else None,
        target_price=Decimal(row.target_price) if row.target_price is not None else None,
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
    cumulative fills attached to its order(s), with the daemon's
    broker-reconciled marks (migration 0040) as the fallback source:

    * ``avg_entry_price`` = fill-weighted ``sum(fill_price * quantity_filled) /
      sum(quantity_filled)``; falls back to the broker's reconciled avgCost
      (``trade.avg_entry_price``) when there are no fills — the case for
      positions whose entry predates IBKR's reqExecutions window.
    * ``last_price`` = latest 1d-bar close from ``market_data_bars`` via
      :class:`DBMarketDataAdapter`, ``None`` when no bars exist.
    * ``unrealized_pnl`` = mark-to-market of the RESOLVED avg vs ``last_price``
      per the buy/sell sign convention (coherent with the displayed avg + last);
      falls back to the broker's reconciled ``trade.unrealized_pnl`` only when
      avg or last is missing. ``None`` when neither resolves.

    Per-symbol cache: 1 SELECT per unique symbol regardless of position
    count. Stale-MD silently degrades to ``None`` — frontend renders "—".

    Sorted ``opened_at DESC``. Empty list when no open trades.
    """
    session_var.set(db)
    trade_repo = TradeRepository()
    fill_repo = FillRepository()
    md_adapter = DBMarketDataAdapter()

    open_rows: list[OpenPositionRow] = await trade_repo.list_open_with_strategy_for_tenant()

    last_price_by_symbol: dict[str, Decimal | None] = {}
    for row in open_rows:
        symbol = row.trade.symbol
        if symbol not in last_price_by_symbol:
            last_price_by_symbol[symbol] = await _fetch_last_price(md_adapter, symbol)

    positions: list[PositionOut] = []
    for row in open_rows:
        trade = row.trade
        fill_avg = await _compute_avg_entry_price(fill_repo, trade.id)
        last_price = last_price_by_symbol[trade.symbol]
        positions.append(_position_from_row(row, fill_avg, last_price))

    log.info(
        "portfolio.positions.fetched",
        tenant_id=str(user.tenant_id),
        position_count=len(positions),
        symbols_with_market_data=sum(1 for v in last_price_by_symbol.values() if v is not None),
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
