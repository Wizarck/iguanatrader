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
