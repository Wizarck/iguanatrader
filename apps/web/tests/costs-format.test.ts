/**
 * Pure tests for `costPerTradeColour` (slice costs-dashboard-ui). DOM-free.
 */

import { describe, expect, it } from 'vitest';

import { costPerTradeColour } from '../src/lib/costs/format';

describe('costPerTradeColour', () => {
  it('returns "destructive" for null (unknown = warning by design)', () => {
    expect(costPerTradeColour(null)).toBe('destructive');
  });

  it('returns "success" for values < 1.0 USD', () => {
    expect(costPerTradeColour(0)).toBe('success');
    expect(costPerTradeColour(0.5)).toBe('success');
    expect(costPerTradeColour(0.99)).toBe('success');
  });

  it('returns "accent" for values between 1.0 and 5.0 USD (inclusive)', () => {
    expect(costPerTradeColour(1.0)).toBe('accent');
    expect(costPerTradeColour(2.49)).toBe('accent');
    expect(costPerTradeColour(5.0)).toBe('accent');
  });

  it('returns "destructive" for values > 5.0 USD', () => {
    expect(costPerTradeColour(5.01)).toBe('destructive');
    expect(costPerTradeColour(7.16)).toBe('destructive');
    expect(costPerTradeColour(100)).toBe('destructive');
  });

  it('returns "destructive" for non-finite values (safety guard)', () => {
    expect(costPerTradeColour(Number.NaN)).toBe('destructive');
    expect(costPerTradeColour(Number.POSITIVE_INFINITY)).toBe('destructive');
  });
});
