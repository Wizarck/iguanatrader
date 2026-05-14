/**
 * Frontend mirrors of the FastAPI Pydantic DTOs in
 * `apps/api/src/iguanatrader/api/dtos/risk.py` (risk surface, slice K1).
 *
 * Decimal fields are serialized as strings by Pydantic v2 → typed as
 * `string` here. `Intl.NumberFormat` is used for DISPLAY ONLY.
 *
 * Once the openapi-typescript pipeline lands real interfaces in
 * `@iguanatrader/shared-types`, this file becomes a thin re-export.
 */

export type CapsDTO = {
  per_trade_pct: string;
  daily_loss_pct: string;
  weekly_loss_pct: string;
  max_open_positions: number;
  max_drawdown_pct: string;
};

export type StateDTO = {
  capital: string;
  day_to_date_loss_pct: string;
  week_to_date_loss_pct: string;
  open_positions_count: number;
  peak_to_trough_drawdown_pct: string;
};

/**
 * `GET /api/v1/risk/state` response body.
 *
 * `utilisation` keys (per backend router impl):
 *   - `daily_loss`     ↔ `caps.daily_loss_pct`
 *   - `weekly_loss`    ↔ `caps.weekly_loss_pct`
 *   - `max_drawdown`   ↔ `caps.max_drawdown_pct`
 *
 * Each value is a Decimal-as-string ratio (e.g. `"0.021"` → 2.1%).
 */
export type RiskStateResponse = {
  caps: CapsDTO;
  state: StateDTO;
  utilisation: Record<string, string>;
  kill_switch_active: boolean;
  fetched_at: string;
};
