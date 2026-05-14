/**
 * Frontend mirrors of the FastAPI Pydantic DTOs in
 * `apps/api/src/iguanatrader/api/dtos/costs.py` (costs surface).
 *
 * Pydantic v2 serialises `Decimal` as string and `datetime` as an ISO
 * 8601 string. Integers (`int`) remain plain JS numbers. Same convention
 * as `$lib/portfolio/types.ts`.
 *
 * Once the `openapi-typescript` pipeline lands real interfaces in
 * `@iguanatrader/shared-types`, this file becomes a thin re-export.
 */

export type PerProviderBreakdown = {
  provider: string;
  cost_usd: string;
  call_count: number;
};

export type CostSummaryDTO = {
  tenant_id: string;
  period_start: string;
  period_end: string;
  total_cost_usd: string;
  total_calls: number;
  cached_calls: number;
};

export type CostByProviderDTO = {
  tenant_id: string;
  period_start: string;
  period_end: string;
  breakdown: PerProviderBreakdown[];
};

export type CostPerTradeDTO = {
  tenant_id: string;
  period_start: string;
  period_end: string;
  total_llm_cost_usd: string;
  closed_trades_count: number;
  cost_per_trade_usd: string | null;
};
