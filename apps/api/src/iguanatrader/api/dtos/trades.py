"""Pydantic v2 DTOs for trades / orders / fills / equity / strategy-configs.

Per design contract: every model sets ``model_config = ConfigDict(
from_attributes=True)`` so it constructs cleanly from a SQLAlchemy ORM
instance (e.g. ``TradeOut.model_validate(trade_orm_instance)``).
``Decimal`` for money columns (Money interop), ``UUID`` for IDs,
``datetime`` for timestamps (Pydantic v2 emits ISO 8601 UTC by default).

Slice T1 plants the shapes; the slice-5 OpenAPI typegen pipeline emits
the matching TypeScript counterparts on first push to
``packages/shared-types/src/index.ts``. T4 wires the route bodies that
return these.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrategyConfigOut(BaseModel):
    """Read projection of :class:`StrategyConfig` (FR1, FR2, FR3, FR4)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    tenant_id: UUID
    strategy_kind: str = Field(examples=["donchian_atr"])
    symbol: str = Field(examples=["SPY"])
    params: dict[str, Any] = Field(
        examples=[{"lookback": 20, "atr_mult": 2.0}],
    )
    enabled: bool = Field(examples=[True])
    version: int = Field(examples=[3])
    created_at: datetime
    updated_at: datetime


class StrategyConfigIn(BaseModel):
    """Write shape for ``PUT /strategies/{symbol}`` (FR2, FR3)."""

    model_config = ConfigDict(extra="forbid")

    strategy_kind: str = Field(examples=["donchian_atr"])
    params: dict[str, Any] = Field(
        examples=[{"lookback": 20, "atr_mult": 2.0}],
    )
    enabled: bool = Field(default=True, examples=[True])


class TradeOut(BaseModel):
    """Read projection of :class:`Trade` (FR46)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    tenant_id: UUID
    proposal_id: UUID
    symbol: str = Field(examples=["SPY"])
    side: str = Field(examples=["buy"])
    quantity: Decimal = Field(examples=[Decimal("10.0")])
    mode: str = Field(examples=["paper"])
    state: str = Field(examples=["open"])
    opened_at: datetime
    closed_at: datetime | None = None
    created_at: datetime


class OrderOut(BaseModel):
    """Read projection of :class:`Order` (FR14, FR15)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    tenant_id: UUID
    trade_id: UUID
    broker: str = Field(examples=["ibkr"])
    broker_order_id: str | None = Field(default=None, examples=["IB-12345"])
    order_type: str = Field(examples=["market"])
    side: str = Field(examples=["buy"])
    quantity: Decimal = Field(examples=[Decimal("10.0")])
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    state: str = Field(examples=["new"])
    submitted_at: datetime | None = None
    acknowledged_at: datetime | None = None
    closed_at: datetime | None = None
    created_at: datetime


class FillOut(BaseModel):
    """Read projection of :class:`Fill` (broker-reported)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    tenant_id: UUID
    order_id: UUID
    quantity_filled: Decimal = Field(examples=[Decimal("10.0")])
    fill_price: Decimal = Field(examples=[Decimal("450.25")])
    commission: Decimal = Field(examples=[Decimal("0.01")])
    commission_currency: str = Field(examples=["USD"])
    filled_at: datetime
    broker_fill_id: str | None = None
    created_at: datetime


class EquitySnapshotOut(BaseModel):
    """Read projection of :class:`EquitySnapshot`."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    tenant_id: UUID
    mode: str = Field(examples=["paper"])
    account_equity: Decimal = Field(examples=[Decimal("100000.00")])
    cash_balance: Decimal = Field(examples=[Decimal("50000.00")])
    realized_pnl_today: Decimal = Field(examples=[Decimal("250.75")])
    unrealized_pnl: Decimal = Field(examples=[Decimal("125.50")])
    currency: str = Field(examples=["USD"])
    snapshot_kind: str = Field(examples=["event"])
    created_at: datetime


class TradeListOut(BaseModel):
    """Paginated list wrapper for :class:`TradeOut`."""

    model_config = ConfigDict(extra="forbid")

    items: list[TradeOut]
    next_cursor: str | None = None
    total: int | None = None


class OrderListOut(BaseModel):
    """Paginated list wrapper for :class:`OrderOut`."""

    model_config = ConfigDict(extra="forbid")

    items: list[OrderOut]
    next_cursor: str | None = None
    total: int | None = None


class FillListOut(BaseModel):
    """Paginated list wrapper for :class:`FillOut`."""

    model_config = ConfigDict(extra="forbid")

    items: list[FillOut]
    next_cursor: str | None = None
    total: int | None = None


class StrategyConfigListOut(BaseModel):
    """List wrapper for :class:`StrategyConfigOut` (FR1)."""

    model_config = ConfigDict(extra="forbid")

    items: list[StrategyConfigOut]
    total: int | None = None


class EquitySnapshotListOut(BaseModel):
    """Paginated list wrapper for :class:`EquitySnapshotOut`."""

    model_config = ConfigDict(extra="forbid")

    items: list[EquitySnapshotOut]
    next_cursor: str | None = None
    total: int | None = None


class PortfolioSummaryOut(BaseModel):
    """Snapshot of the current portfolio state (latest equity + open trades).

    Slice T4 fills the GET /portfolio body; T1 plants the shape so the
    OpenAPI surface + TS interface are stable from the start.
    """

    model_config = ConfigDict(extra="forbid")

    equity: EquitySnapshotOut
    open_trades: list[TradeOut]
    open_orders: list[OrderOut]


class PositionOut(BaseModel):
    """Derived position projection — one row per open :class:`Trade`.

    Computed at read time from open trades plus their cumulative fills.
    ``last_price`` and ``unrealized_pnl`` are intentionally null in v1;
    a follow-up slice (``market-data-snapshot-port``) wires the market-
    data hook that populates them.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=False)

    trade_id: UUID
    symbol: str = Field(examples=["SPY"])
    side: str = Field(examples=["buy"])
    quantity: Decimal = Field(examples=[Decimal("10.0")])
    avg_entry_price: Decimal | None = Field(
        default=None,
        examples=[Decimal("450.25")],
    )
    last_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    opened_at: datetime


class PositionListOut(BaseModel):
    """List wrapper for :class:`PositionOut`."""

    model_config = ConfigDict(extra="forbid")

    items: list[PositionOut]
    total: int | None = None


__all__ = [
    "EquitySnapshotListOut",
    "EquitySnapshotOut",
    "FillListOut",
    "FillOut",
    "OrderListOut",
    "OrderOut",
    "PortfolioSummaryOut",
    "PositionListOut",
    "PositionOut",
    "StrategyConfigIn",
    "StrategyConfigListOut",
    "StrategyConfigOut",
    "TradeListOut",
    "TradeOut",
]
