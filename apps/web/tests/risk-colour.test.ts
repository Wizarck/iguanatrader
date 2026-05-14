/**
 * Pure tests for `utilisationBarColour` (slice risk-dashboard-ui).
 * DOM-free.
 */

import { describe, expect, it } from 'vitest';

import { utilisationBarColour } from '../src/lib/risk/colour';

describe('utilisationBarColour', () => {
  it('returns "success" for ratios strictly below 0.5', () => {
    expect(utilisationBarColour(0)).toBe('success');
    expect(utilisationBarColour(0.1)).toBe('success');
    expect(utilisationBarColour(0.49)).toBe('success');
  });

  it('returns "accent" for ratios in the 0.5..0.8 band (inclusive)', () => {
    expect(utilisationBarColour(0.5)).toBe('accent');
    expect(utilisationBarColour(0.65)).toBe('accent');
    expect(utilisationBarColour(0.8)).toBe('accent');
  });

  it('returns "destructive" for ratios strictly above 0.8', () => {
    expect(utilisationBarColour(0.81)).toBe('destructive');
    expect(utilisationBarColour(0.9)).toBe('destructive');
    expect(utilisationBarColour(1)).toBe('destructive');
    expect(utilisationBarColour(1.5)).toBe('destructive');
  });

  it('coerces NaN / Infinity to "destructive" defensively', () => {
    expect(utilisationBarColour(Number.NaN)).toBe('destructive');
    expect(utilisationBarColour(Number.POSITIVE_INFINITY)).toBe('destructive');
    expect(utilisationBarColour(Number.NEGATIVE_INFINITY)).toBe('destructive');
  });
});
