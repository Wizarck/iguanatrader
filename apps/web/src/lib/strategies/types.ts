/**
 * Frontend mirrors of the FastAPI Pydantic DTOs in
 * `apps/api/src/iguanatrader/api/dtos/trades.py` (`StrategyConfigOut`,
 * `StrategyConfigIn`, `StrategyConfigListOut`).
 *
 * Same shape contract as `$lib/trades/types.ts` + `$lib/portfolio/types.ts`:
 * UUIDs as strings, timestamps as ISO 8601 strings, Pydantic dicts as
 * `Record<string, unknown>` (we never read into them on the frontend in v1).
 */

export type StrategyConfigOut = {
  id: string;
  tenant_id: string;
  strategy_kind: string;
  symbol: string;
  params: Record<string, unknown>;
  enabled: boolean;
  version: number;
  created_at: string;
  updated_at: string;
};

export type StrategyConfigIn = {
  strategy_kind: string;
  params: Record<string, unknown>;
  enabled: boolean;
};

export type StrategyConfigListOut = {
  items: StrategyConfigOut[];
  total: number | null;
};

/**
 * Strategy kinds hard-coded in v1 (matches
 * `apps/api/src/iguanatrader/contexts/trading/strategies/`). When v1.5+
 * adds more kinds, a `GET /strategies/catalogue` endpoint becomes the
 * source. For 2 kinds, hard-coding ships.
 */
export const STRATEGY_KINDS = ['donchian_atr', 'sma_cross'] as const;
export type StrategyKind = (typeof STRATEGY_KINDS)[number];

/** Default params per strategy kind — used to seed the JSON textarea. */
export const STRATEGY_KIND_DEFAULTS: Record<StrategyKind, Record<string, unknown>> = {
  donchian_atr: { lookback: 20, atr_mult: 2.0 },
  sma_cross: { fast: 50, slow: 200 },
};

/** Pretty JSON used as textarea default when a kind is selected. */
export function defaultParamsJson(kind: StrategyKind): string {
  return JSON.stringify(STRATEGY_KIND_DEFAULTS[kind], null, 2);
}

/** IBKR symbol convention — uppercase A-Z and digits, length 1..16. */
export const SYMBOL_PATTERN = /^[A-Z0-9]{1,16}$/;
