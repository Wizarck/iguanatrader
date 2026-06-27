/**
 * Pure display-only helpers for portfolio Decimal-as-string values.
 *
 * Backend serializes Decimal fields as strings (Pydantic v2 default).
 * `Intl.NumberFormat` is used for DISPLAY ONLY — never for arithmetic.
 * Live in a separate module so they are unit-testable without a DOM.
 */

/**
 * Non-ISO currency-code aliases. IBKR's consolidated account summary
 * reports the base-currency equity row with the literal sentinel
 * `"BASE"` (not an ISO 4217 code), which `Intl.NumberFormat` rejects with
 * a `RangeError`. The paper/live accounts are USD-denominated, so map it.
 */
const CURRENCY_ALIASES: Record<string, string> = { BASE: 'USD' };

/**
 * Format a Decimal-as-string money value for display.
 *
 * @param value - Decimal-as-string (e.g. `"237.45"`); `null` returns `"—"`.
 * @param currency - ISO 4217 currency code (e.g. `"USD"`).
 * @returns Formatted money string (e.g. `"$237.45"`), or `"—"` for null.
 *
 * Never throws on a malformed currency code: an unknown/non-ISO code
 * (after alias resolution) falls back to a plain 2-decimal number so a
 * single bad code can't 500 the whole page (regression: IBKR `"BASE"`).
 */
export function formatMoney(value: string | null, currency: string): string {
  if (value === null) return '—';
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  const code = CURRENCY_ALIASES[currency] ?? currency;
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: code,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(parsed);
  } catch {
    return parsed.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
}

/**
 * Format a Decimal-as-string ratio for display as a signed percentage.
 *
 * @param value - Decimal-as-string ratio (e.g. `"0.0024"` ⇒ `"+0.24%"`);
 *   `null` returns `"—"`.
 * @returns Signed percentage string (e.g. `"+0.24%"`, `"-1.50%"`, `"0.00%"`).
 */
export function formatPercent(value: string | null): string {
  if (value === null) return '—';
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  const pct = parsed * 100;
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}
