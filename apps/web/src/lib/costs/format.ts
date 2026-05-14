/**
 * Pure helpers for the costs dashboard (slice costs-dashboard-ui).
 *
 * DOM-free. Lives in a separate module so it is unit-testable.
 */

/**
 * Map a `cost_per_trade_usd` numeric value to a UI tier colour token.
 *
 * Rationale: `null` (no closed trades yet) is rendered as "unknown =
 * warning" so the operator investigates — explicitly NOT a neutral
 * tone. High values (>5 USD per trade) and `null` both map to
 * `destructive`.
 *
 * @param value - Parsed numeric `cost_per_trade_usd`, or `null` when the
 *   backend reports no closed trades (denominator zero).
 * @returns Tier label aligned with the OKLCH semantic tokens
 *   `--success` / `--accent` / `--destructive`.
 */
export function costPerTradeColour(
  value: number | null,
): 'success' | 'accent' | 'destructive' {
  if (value === null || !Number.isFinite(value)) return 'destructive';
  if (value < 1.0) return 'success';
  if (value <= 5.0) return 'accent';
  return 'destructive';
}
