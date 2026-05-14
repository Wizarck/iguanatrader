/**
 * Pure display-only helpers for portfolio Decimal-as-string values.
 *
 * Backend serializes Decimal fields as strings (Pydantic v2 default).
 * `Intl.NumberFormat` is used for DISPLAY ONLY — never for arithmetic.
 * Live in a separate module so they are unit-testable without a DOM.
 */

/**
 * Format a Decimal-as-string money value for display.
 *
 * @param value - Decimal-as-string (e.g. `"237.45"`); `null` returns `"—"`.
 * @param currency - ISO 4217 currency code (e.g. `"USD"`).
 * @returns Formatted money string (e.g. `"$237.45"`), or `"—"` for null.
 */
export function formatMoney(value: string | null, currency: string): string {
  if (value === null) return '—';
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(parsed);
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
