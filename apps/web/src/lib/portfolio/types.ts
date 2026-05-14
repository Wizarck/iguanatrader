/**
 * Frontend mirrors of the FastAPI Pydantic DTOs in
 * `apps/api/src/iguanatrader/api/dtos/trades.py` (portfolio surface).
 *
 * Same Decimal-as-string + ISO 8601 datetime-as-string conventions as
 * `$lib/trades/types.ts`. Once openapi-typescript pipeline lands real
 * interfaces in `@iguanatrader/shared-types`, this file becomes a thin
 * re-export.
 */

import type { OrderOut, TradeOut } from '$lib/trades/types';

export type EquitySnapshotOut = {
  id: string;
  tenant_id: string;
  mode: string;
  account_equity: string;
  cash_balance: string;
  realized_pnl_today: string;
  unrealized_pnl: string;
  currency: string;
  snapshot_kind: string;
  created_at: string;
};

export type EquitySnapshotListOut = {
  items: EquitySnapshotOut[];
  next_cursor: string | null;
  total: number | null;
};

export type PortfolioSummaryOut = {
  equity: EquitySnapshotOut;
  open_trades: TradeOut[];
  open_orders: OrderOut[];
  day_pnl_abs: string | null;
  day_pnl_pct: string | null;
};

export type PositionOut = {
  trade_id: string;
  symbol: string;
  side: string;
  quantity: string;
  avg_entry_price: string | null;
  last_price: string | null;
  unrealized_pnl: string | null;
  opened_at: string;
};

export type PositionListOut = {
  items: PositionOut[];
  total: number | null;
};
