/**
 * Trade-variant helpers (slice u-next-2-trade-timeline).
 *
 * Pure-function tests pinning the contract used by the trade-detail
 * page so a future refactor of `variants.ts` can't silently swap
 * `closing` and `closed` back to the same Badge variant (the
 * original bug the slice was opened to fix).
 */

import { describe, expect, it } from 'vitest';

import {
  orderRoleLabel,
  orderStateVariant,
  sideVariant,
  stateVariant,
} from '../src/lib/trades/variants';

describe('sideVariant', () => {
  it('maps buy → success and sell → destructive', () => {
    expect(sideVariant('buy')).toBe('success');
    expect(sideVariant('sell')).toBe('destructive');
  });
});

describe('stateVariant', () => {
  it('returns accent for open trades', () => {
    expect(stateVariant('open')).toBe('accent');
  });

  it('returns warning for closing trades (active exit-order risk)', () => {
    // The whole reason this slice exists: closing != closed visually.
    expect(stateVariant('closing')).toBe('warning');
  });

  it('returns mute for closed trades (terminal)', () => {
    expect(stateVariant('closed')).toBe('mute');
  });

  it('falls back to mute for unknown states', () => {
    expect(stateVariant('weird-state')).toBe('mute');
  });

  it('closing and closed produce different variants', () => {
    // Regression pin — pre-slice both returned `mute`.
    expect(stateVariant('closing')).not.toBe(stateVariant('closed'));
  });
});

describe('orderStateVariant', () => {
  it('maps the IBKR-side lifecycle to Badge variants', () => {
    expect(orderStateVariant('new')).toBe('mute');
    expect(orderStateVariant('submitted')).toBe('warning');
    expect(orderStateVariant('partially_filled')).toBe('warning');
    expect(orderStateVariant('filled')).toBe('success');
    expect(orderStateVariant('canceled')).toBe('destructive');
    expect(orderStateVariant('rejected')).toBe('destructive');
  });

  it('falls back to mute for unknown states', () => {
    expect(orderStateVariant('whatever')).toBe('mute');
  });
});

describe('orderRoleLabel', () => {
  it('labels same-side market orders as Entry', () => {
    expect(orderRoleLabel('buy', 'market', 'buy')).toBe('Entry');
    expect(orderRoleLabel('sell', 'market', 'sell')).toBe('Entry');
  });

  it('labels opposite-side stop orders as Stop', () => {
    expect(orderRoleLabel('sell', 'stop', 'buy')).toBe('Stop');
    expect(orderRoleLabel('buy', 'stop', 'sell')).toBe('Stop');
  });

  it('labels opposite-side limit orders as Target', () => {
    expect(orderRoleLabel('sell', 'limit', 'buy')).toBe('Target');
    expect(orderRoleLabel('buy', 'limit', 'sell')).toBe('Target');
  });

  it('labels opposite-side market orders as Exit', () => {
    expect(orderRoleLabel('sell', 'market', 'buy')).toBe('Exit');
    expect(orderRoleLabel('buy', 'market', 'sell')).toBe('Exit');
  });

  it('falls back to the order_type when no rule matches', () => {
    expect(orderRoleLabel('buy', 'unusual_kind', 'buy')).toBe('unusual_kind');
  });
});
