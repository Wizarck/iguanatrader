/**
 * Catalogue invariants for `apps/web/src/lib/strategies/types.ts`.
 *
 * Locks in the contract the dynamic form depends on:
 *
 *   1. Every strategy_kind in the catalogue has at least one parameter.
 *   2. `validateParamForm` rejects blank required fields with `is required`.
 *   3. `validateParamForm` rejects non-integer values for integer params.
 *   4. `validateParamForm` rejects out-of-range values.
 *   5. `percent` params round-trip: display 1.0 ↔ backend 0.01.
 *   6. `optional-*` params left blank are omitted from the params payload.
 *   7. `defaultParams(kind)` matches the Python `DEFAULT_*` constants
 *      for the two strategies we have hard-coded examples of (donchian_atr,
 *      sma_cross) — sentinel against silent drift.
 */

import { describe, expect, it } from 'vitest';

import {
  STRATEGY_CATALOGUE,
  STRATEGY_KINDS,
  defaultParams,
  getStrategySpec,
  paramsToFormValues,
  validateParamForm,
} from '../src/lib/strategies/types';

describe('STRATEGY_CATALOGUE', () => {
  it('exposes all six backend strategy kinds', () => {
    expect(STRATEGY_KINDS).toEqual(
      expect.arrayContaining([
        'donchian_atr',
        'sma_cross',
        'bollinger_breakout',
        'rsi_mean_reversion',
        'macd_cross',
        'volume_donchian',
      ]),
    );
  });

  it('every kind has at least one parameter', () => {
    for (const spec of STRATEGY_CATALOGUE) {
      expect(spec.params.length).toBeGreaterThan(0);
    }
  });

  it('every kind has a non-empty description and displayName', () => {
    for (const spec of STRATEGY_CATALOGUE) {
      expect(spec.description.length).toBeGreaterThan(20);
      expect(spec.displayName.length).toBeGreaterThan(0);
    }
  });

  it('donchian_atr defaults match the Python source of truth', () => {
    expect(defaultParams('donchian_atr')).toEqual({
      lookback: 20,
      atr_period: 14,
      atr_mult: 2.0,
      risk_pct: 0.01,
    });
  });

  it('sma_cross defaults match the Python source of truth', () => {
    expect(defaultParams('sma_cross')).toEqual({
      fast: 50,
      slow: 200,
      vol_window: 20,
      risk_pct: 0.01,
    });
  });
});

describe('validateParamForm', () => {
  it('rejects blank required fields with "is required"', () => {
    const spec = getStrategySpec('donchian_atr')!;
    const result = validateParamForm(spec, { lookback: '', atr_period: '14', atr_mult: '2', risk_pct: '1' });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.lookback).toMatch(/is required/i);
    }
  });

  it('rejects non-integer values for integer params', () => {
    const spec = getStrategySpec('donchian_atr')!;
    const result = validateParamForm(spec, {
      lookback: '20.5',
      atr_period: '14',
      atr_mult: '2',
      risk_pct: '1',
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.lookback).toMatch(/whole number/i);
    }
  });

  it('rejects out-of-range values', () => {
    const spec = getStrategySpec('donchian_atr')!;
    const result = validateParamForm(spec, {
      lookback: '500', // max is 200
      atr_period: '14',
      atr_mult: '2',
      risk_pct: '1',
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.lookback).toMatch(/at most 200/i);
    }
  });

  it('round-trips percent params: display 1.0 ↔ backend 0.01', () => {
    const spec = getStrategySpec('donchian_atr')!;
    const result = validateParamForm(spec, {
      lookback: '20',
      atr_period: '14',
      atr_mult: '2',
      risk_pct: '1',
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.params.risk_pct).toBeCloseTo(0.01, 8);
    }
  });

  it('omits blank optional-decimal fields from the payload', () => {
    const spec = getStrategySpec('bollinger_breakout')!;
    const result = validateParamForm(spec, {
      period: '20',
      num_std: '2',
      squeeze_threshold: '',
      squeeze_lookback: '6',
      atr_period: '14',
      atr_mult: '2',
      risk_pct: '1',
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.params).not.toHaveProperty('squeeze_threshold');
    }
  });

  it('keeps populated optional-decimal fields in the payload', () => {
    const spec = getStrategySpec('bollinger_breakout')!;
    const result = validateParamForm(spec, {
      period: '20',
      num_std: '2',
      squeeze_threshold: '0.05',
      squeeze_lookback: '6',
      atr_period: '14',
      atr_mult: '2',
      risk_pct: '1',
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.params.squeeze_threshold).toBeCloseTo(0.05);
    }
  });

  it('omits blank optional-string fields from the payload', () => {
    const spec = getStrategySpec('macd_cross')!;
    const result = validateParamForm(spec, {
      fast: '12',
      slow: '26',
      signal: '9',
      bias_filter: '',
      atr_period: '14',
      atr_mult: '2',
      risk_pct: '1',
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.params).not.toHaveProperty('bias_filter');
    }
  });
});

describe('paramsToFormValues', () => {
  it('converts backend percent fraction back to display value', () => {
    const spec = getStrategySpec('donchian_atr')!;
    const values = paramsToFormValues(spec, {
      lookback: 20,
      atr_period: 14,
      atr_mult: 2.0,
      risk_pct: 0.015,
    });
    expect(values.risk_pct).toBe('1.5');
  });

  it('seeds defaults for params not present in the input', () => {
    const spec = getStrategySpec('donchian_atr')!;
    const values = paramsToFormValues(spec, { lookback: 30 });
    expect(values.lookback).toBe('30');
    expect(values.atr_period).toBe('14'); // catalogue default
  });

  it('leaves optional fields blank when omitted', () => {
    const spec = getStrategySpec('bollinger_breakout')!;
    const values = paramsToFormValues(spec, { period: 25 });
    expect(values.squeeze_threshold).toBe('');
  });
});
