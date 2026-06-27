/**
 * Pure tests for `formatMoney` + `formatPercent`
 * (slice portfolio-dashboard-mvp). DOM-free.
 */

import { describe, expect, it } from 'vitest';

import { formatMoney, formatPercent } from '../src/lib/portfolio/format';

describe('formatMoney', () => {
  it('formats a positive USD value with thousands separator', () => {
    expect(formatMoney('237.45', 'USD')).toBe('$237.45');
    expect(formatMoney('100237.45', 'USD')).toBe('$100,237.45');
  });

  it('returns "—" for null', () => {
    expect(formatMoney(null, 'USD')).toBe('—');
  });

  it('formats zero correctly', () => {
    expect(formatMoney('0', 'USD')).toBe('$0.00');
    expect(formatMoney('0.00', 'USD')).toBe('$0.00');
  });

  it('formats a negative value', () => {
    expect(formatMoney('-150.25', 'USD')).toBe('-$150.25');
  });

  it('returns "—" for an unparseable value', () => {
    expect(formatMoney('not-a-number', 'USD')).toBe('—');
  });

  it('aliases IBKR\'s "BASE" sentinel to USD instead of crashing', () => {
    // Regression: equity_snapshots.currency === "BASE" (IBKR consolidated
    // base-currency row) 500'd the whole /portfolio page via a RangeError.
    expect(formatMoney('1234.5', 'BASE')).toBe('$1,234.50');
  });

  it('falls back to a plain number for a malformed currency code (no throw)', () => {
    // Not a 3-letter code → Intl.NumberFormat throws RangeError → fallback.
    expect(formatMoney('1234.5', 'US')).toBe('1,234.50');
  });
});

describe('formatPercent', () => {
  it('formats a positive ratio with a + sign', () => {
    expect(formatPercent('0.0024')).toBe('+0.24%');
  });

  it('formats a negative ratio (no extra sign — minus is intrinsic)', () => {
    expect(formatPercent('-0.0150')).toBe('-1.50%');
  });

  it('formats zero unsigned', () => {
    expect(formatPercent('0')).toBe('0.00%');
    expect(formatPercent('0.0')).toBe('0.00%');
  });

  it('returns "—" for null', () => {
    expect(formatPercent(null)).toBe('—');
  });

  it('returns "—" for an unparseable value', () => {
    expect(formatPercent('not-a-number')).toBe('—');
  });
});
