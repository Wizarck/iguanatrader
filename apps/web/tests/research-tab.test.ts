/**
 * `research-tab-ui` slice — behavior tests covering the landing-page
 * contract end-to-end without rendering Svelte components (the project
 * vitest env is `node`; component rendering is covered by Storybook +
 * Playwright e2e).
 *
 * The five scenarios from the proposal §Tests are exercised against
 * the public surface of `$lib/research/recent.ts` (read / record /
 * write) and the symbol-validator that drives `SymbolSearchCard`'s
 * onSubmit guard:
 *
 *   1. Empty localStorage → `readRecent` returns [], so the consuming
 *      component renders the `EmptyState` branch.
 *   2. Valid symbol entered → passes `isValidSymbol`, allowing the
 *      default `goto('/research/{symbol}')` path.
 *   3. Invalid symbol pattern → `isValidSymbol` rejects, so the card
 *      keeps the inline error visible and never navigates.
 *   4. localStorage seeded with N symbols → `readRecent` returns those
 *      N symbols, the list renders N pills.
 *   5. localStorage corrupted (non-JSON) → falls back to empty list,
 *      no crash.
 *
 * Plus the detail-page `$effect` hook contract (read → recordRecent →
 * write) is exercised as a single round-trip.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  isValidSymbol,
  readRecent,
  recordRecent,
  writeRecent
} from '../src/lib/research/recent';

const STORAGE_KEY = 'iguanatrader.research.recent';

function makeMockStorage(seed: Record<string, string> = {}) {
  const store = new Map<string, string>(Object.entries(seed));
  return {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => {
      store.set(k, v);
    },
    removeItem: (k: string) => {
      store.delete(k);
    },
    clear: () => {
      store.clear();
    },
    _store: store
  };
}

describe('research landing tab — contract', () => {
  let storage: ReturnType<typeof makeMockStorage>;

  beforeEach(() => {
    storage = makeMockStorage();
    vi.stubGlobal('window', { localStorage: storage });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('case 1 — empty localStorage drives the EmptyState branch', () => {
    // No prior writes → list is empty → consumer renders EmptyState.
    expect(readRecent(STORAGE_KEY)).toEqual([]);
  });

  it('case 2 — valid symbol clears the validator gate', () => {
    // SymbolSearchCard normalises (`trim().toUpperCase()`) then checks.
    const raw = '  spy ';
    const normalised = raw.trim().toUpperCase();
    expect(isValidSymbol(normalised)).toBe(true);
    // The default handler would call `goto('/research/' + normalised)`.
    expect(`/research/${normalised}`).toBe('/research/SPY');
  });

  it('case 3 — invalid symbol pattern keeps inline error and skips navigation', () => {
    expect(isValidSymbol('spy lower!')).toBe(false);
    expect(isValidSymbol('')).toBe(false);
    expect(isValidSymbol('TOOLONGGGGGGGGGGGG')).toBe(false);
  });

  it('case 4 — seeded localStorage renders N pills (N=3)', () => {
    storage._store.set(STORAGE_KEY, JSON.stringify(['SPY', 'QQQ', 'TSLA']));
    expect(readRecent(STORAGE_KEY)).toEqual(['SPY', 'QQQ', 'TSLA']);
  });

  it('case 5 — corrupted localStorage falls back to [] without throwing', () => {
    storage._store.set(STORAGE_KEY, '{not json');
    expect(() => readRecent(STORAGE_KEY)).not.toThrow();
    expect(readRecent(STORAGE_KEY)).toEqual([]);
  });
});

describe('detail-page $effect contract — read → recordRecent → write', () => {
  let storage: ReturnType<typeof makeMockStorage>;

  beforeEach(() => {
    storage = makeMockStorage();
    vi.stubGlobal('window', { localStorage: storage });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function runEffect(symbol: string): void {
    const next = recordRecent(readRecent(STORAGE_KEY), symbol);
    writeRecent(STORAGE_KEY, next);
  }

  it('first visit seeds the list with the symbol', () => {
    runEffect('SPY');
    expect(readRecent(STORAGE_KEY)).toEqual(['SPY']);
  });

  it('subsequent visit prepends new symbol, dedupe-aware', () => {
    runEffect('SPY');
    runEffect('QQQ');
    runEffect('SPY'); // moves SPY back to front
    expect(readRecent(STORAGE_KEY)).toEqual(['SPY', 'QQQ']);
  });

  it('caps the persisted list at 8 entries (FIFO with newest-first)', () => {
    for (const s of [
      'AAA',
      'BBB',
      'CCC',
      'DDD',
      'EEE',
      'FFF',
      'GGG',
      'HHH',
      'III'
    ]) {
      runEffect(s);
    }
    const stored = readRecent(STORAGE_KEY);
    // Slice U4: DEFAULT_MAX_RECENT lowered from 8 → 5.
    expect(stored).toHaveLength(5);
    expect(stored[0]).toBe('III');
    expect(stored).not.toContain('AAA'); // oldest dropped
    expect(stored).not.toContain('DDD'); // also dropped (now beyond the cap)
  });

  it('survives corrupted prior storage by treating it as empty', () => {
    storage._store.set(STORAGE_KEY, '{corrupt');
    runEffect('SPY');
    expect(readRecent(STORAGE_KEY)).toEqual(['SPY']);
  });

  it('ignores invalid symbols without polluting storage', () => {
    runEffect('SPY');
    runEffect('not a symbol');
    expect(readRecent(STORAGE_KEY)).toEqual(['SPY']);
  });
});
