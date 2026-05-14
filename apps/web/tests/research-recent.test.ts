/**
 * Pure-helper tests for `$lib/research/recent.ts` (slice
 * `research-tab-ui`).
 *
 * The two impure browser helpers (`readRecent` / `writeRecent`) are
 * covered via `vi.stubGlobal('localStorage', ...)`. The pure
 * `parseRecent` + `recordRecent` + `isValidSymbol` exports are tested
 * directly without any DOM stand-in.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DEFAULT_MAX_RECENT,
  isValidSymbol,
  parseRecent,
  readRecent,
  recordRecent,
  writeRecent
} from '../src/lib/research/recent';

describe('isValidSymbol', () => {
  it('accepts uppercase letter + digit symbols 1-16 chars', () => {
    expect(isValidSymbol('SPY')).toBe(true);
    expect(isValidSymbol('A')).toBe(true);
    expect(isValidSymbol('BRK')).toBe(true);
    expect(isValidSymbol('BTC2024')).toBe(true);
    expect(isValidSymbol('ABCDEFGHIJKLMNOP')).toBe(true); // 16
  });

  it('rejects lowercase / spaces / punctuation / empty / overflow', () => {
    expect(isValidSymbol('')).toBe(false);
    expect(isValidSymbol('spy')).toBe(false);
    expect(isValidSymbol('SP Y')).toBe(false);
    expect(isValidSymbol('BRK.B')).toBe(false);
    expect(isValidSymbol('ABCDEFGHIJKLMNOPQ')).toBe(false); // 17
    expect(isValidSymbol('SPY!')).toBe(false);
  });
});

describe('parseRecent', () => {
  it('returns [] for null / undefined / empty string', () => {
    expect(parseRecent(null)).toEqual([]);
    expect(parseRecent('')).toEqual([]);
  });

  it('returns [] on malformed JSON', () => {
    expect(parseRecent('{not json')).toEqual([]);
    expect(parseRecent('not even close')).toEqual([]);
  });

  it('returns [] when parsed value is not an array', () => {
    expect(parseRecent('{}')).toEqual([]);
    expect(parseRecent('"SPY"')).toEqual([]);
    expect(parseRecent('123')).toEqual([]);
    expect(parseRecent('null')).toEqual([]);
  });

  it('filters non-string elements from an array', () => {
    expect(parseRecent('["SPY", 42, null, "QQQ", true, "TSLA"]')).toEqual([
      'SPY',
      'QQQ',
      'TSLA'
    ]);
  });

  it('round-trips a clean array', () => {
    expect(parseRecent('["SPY","QQQ","TSLA"]')).toEqual(['SPY', 'QQQ', 'TSLA']);
  });
});

describe('recordRecent', () => {
  it('prepends a new symbol to an empty list', () => {
    expect(recordRecent([], 'SPY')).toEqual(['SPY']);
  });

  it('coerces input to uppercase and trims whitespace', () => {
    expect(recordRecent([], '  spy  ')).toEqual(['SPY']);
  });

  it('dedupes case-insensitively and re-prepends', () => {
    expect(recordRecent(['QQQ', 'SPY', 'TSLA'], 'spy')).toEqual([
      'SPY',
      'QQQ',
      'TSLA'
    ]);
  });

  it('caps the list at max (default 8)', () => {
    const list = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];
    expect(recordRecent(list, 'I')).toEqual([
      'I',
      'A',
      'B',
      'C',
      'D',
      'E',
      'F',
      'G'
    ]);
  });

  it('honours a custom max', () => {
    expect(recordRecent(['A', 'B', 'C'], 'D', 2)).toEqual(['D', 'A']);
  });

  it('returns the list unchanged (cloned) when the new symbol is invalid', () => {
    const list = ['SPY', 'QQQ'];
    const out = recordRecent(list, 'not a symbol');
    expect(out).toEqual(list);
    expect(out).not.toBe(list); // cloned
  });

  it('uses DEFAULT_MAX_RECENT === 8', () => {
    expect(DEFAULT_MAX_RECENT).toBe(8);
  });
});

// ---------------------------------------------------------------------------
// Browser glue: readRecent / writeRecent
// ---------------------------------------------------------------------------

function makeMockStorage(seed: Record<string, string> = {}) {
  const store = new Map<string, string>(Object.entries(seed));
  return {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: vi.fn((k: string, v: string) => {
      store.set(k, v);
    }),
    removeItem: (k: string) => {
      store.delete(k);
    },
    clear: () => {
      store.clear();
    },
    _store: store
  };
}

const STORAGE_KEY = 'iguanatrader.research.recent';

describe('readRecent (browser glue)', () => {
  let storage: ReturnType<typeof makeMockStorage>;

  beforeEach(() => {
    storage = makeMockStorage();
    vi.stubGlobal('window', { localStorage: storage });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns [] when storage is empty', () => {
    expect(readRecent(STORAGE_KEY)).toEqual([]);
  });

  it('returns parsed list when storage has a clean payload', () => {
    storage._store.set(STORAGE_KEY, JSON.stringify(['SPY', 'QQQ']));
    expect(readRecent(STORAGE_KEY)).toEqual(['SPY', 'QQQ']);
  });

  it('returns [] when storage payload is corrupted', () => {
    storage._store.set(STORAGE_KEY, '{not json');
    expect(readRecent(STORAGE_KEY)).toEqual([]);
  });

  it('returns [] when localStorage.getItem throws', () => {
    vi.stubGlobal('window', {
      localStorage: {
        getItem: () => {
          throw new Error('blocked');
        }
      }
    });
    expect(readRecent(STORAGE_KEY)).toEqual([]);
  });
});

describe('writeRecent (browser glue)', () => {
  let storage: ReturnType<typeof makeMockStorage>;

  beforeEach(() => {
    storage = makeMockStorage();
    vi.stubGlobal('window', { localStorage: storage });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('writes a JSON-stringified list to the given key', () => {
    writeRecent(STORAGE_KEY, ['SPY', 'QQQ']);
    expect(storage.setItem).toHaveBeenCalledWith(
      STORAGE_KEY,
      JSON.stringify(['SPY', 'QQQ'])
    );
  });

  it('silently no-ops when localStorage.setItem throws', () => {
    vi.stubGlobal('window', {
      localStorage: {
        setItem: () => {
          throw new Error('quota');
        }
      }
    });
    expect(() => writeRecent(STORAGE_KEY, ['SPY'])).not.toThrow();
  });
});
