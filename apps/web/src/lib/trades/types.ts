/**
 * Frontend mirrors of the FastAPI Pydantic DTOs in
 * `apps/api/src/iguanatrader/api/dtos/trades.py`. Once the
 * openapi-typescript pipeline lands real interfaces in
 * `@iguanatrader/shared-types`, this file is a thin re-export.
 *
 * Decimals serialize as strings over JSON (Pydantic v2 default),
 * timestamps as ISO 8601 strings.
 */

export type TradeOut = {
  id: string;
  tenant_id: string;
  proposal_id: string;
  symbol: string;
  side: string;
  quantity: string;
  mode: string;
  state: string;
  opened_at: string;
  closed_at: string | null;
  created_at: string;
  // Slice ``frontend-gaps-batch``: A3 auto-journal writes here on
  // TradeClosed; the trade-detail page reads it to render the
  // post-mortem section. NULL until A3 fires (or the manual journal
  // endpoint is POSTed).
  exit_reason?: string | null;
  realised_pnl?: string | null;
  journal_narrative?: string | null;
  journal_generated_at?: string | null;
  journal_model?: string | null;
};

export type OrderOut = {
  id: string;
  tenant_id: string;
  trade_id: string;
  broker: string;
  broker_order_id: string | null;
  order_type: string;
  side: string;
  quantity: string;
  limit_price: string | null;
  stop_price: string | null;
  state: string;
  submitted_at: string | null;
  acknowledged_at: string | null;
  closed_at: string | null;
  created_at: string;
};

export type FillOut = {
  id: string;
  tenant_id: string;
  order_id: string;
  quantity_filled: string;
  fill_price: string;
  commission: string;
  commission_currency: string;
  filled_at: string;
  broker_fill_id: string | null;
  created_at: string;
};

export type TradeListOut = {
  items: TradeOut[];
  next_cursor: string | null;
  total: number | null;
};

export type FillListOut = {
  items: FillOut[];
  next_cursor: string | null;
  total: number | null;
};

export type OrderListOut = {
  items: OrderOut[];
  next_cursor: string | null;
  total: number | null;
};
