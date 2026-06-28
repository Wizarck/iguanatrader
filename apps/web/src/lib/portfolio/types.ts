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
  // REAL average entry: fill-weighted when fills exist, else the broker's
  // reconciled avgCost. Null only when neither is available.
  avg_entry_price: string | null;
  last_price: string | null;
  // Broker-reconciled mark-to-market when present, else computed from
  // avg_entry_price vs last_price.
  unrealized_pnl: string | null;
  // When the broker-reconciled marks (avg/uPnL) were last refreshed; null when
  // the figures come purely from local fills + market data.
  marks_updated_at: string | null;
  opened_at: string;
  // Plan-of-record from the originating proposal/strategy (already in the DB).
  // `entry_price_indicative` = INTENDED entry, distinct from the filled
  // `avg_entry_price`. All null only if the proposal/config was purged.
  strategy_kind: string | null;
  entry_price_indicative: string | null;
  stop_price: string | null;
  target_price: string | null;
};

export type PositionListOut = {
  items: PositionOut[];
  total: number | null;
};
