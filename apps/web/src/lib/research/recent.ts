/**
 * Recent-symbols helpers — slice `research-tab-ui`.
 *
 * The pure parse / dedupe logic lives here so it is unit-testable
 * without a DOM. The thin localStorage glue (`readRecent` /
 * `writeRecent`) is SSR-safe: every browser call is gated on
 * `typeof window !== 'undefined'` and wrapped in try/catch (privacy
 * mode, quota, or disabled storage all return safe defaults).
 *
 * Storage shape: JSON-encoded array of uppercase symbol strings, e.g.
 * `["SPY","QQQ","TSLA"]`. The list is FIFO with newest-first, deduped
 * case-insensitively, and capped at `max` entries (default 8).
 *
 * v1.5 may swap this for a server-backed watchlist
 * (`research-watchlist-endpoint`); the in-memory list shape stays
 * compatible.
 */

export const DEFAULT_MAX_RECENT = 8;

/** Symbol input pattern — matches strategies-config-ui (IBKR convention). */
export const SYMBOL_PATTERN = /^[A-Z0-9]{1,16}$/;

/**
 * Validate a symbol string against the canonical pattern.
 * Caller is responsible for trimming + uppercasing before calling.
 */
export function isValidSymbol(symbol: string): boolean {
  return SYMBOL_PATTERN.test(symbol);
}

/**
 * Pure parser — given raw localStorage payload (string or null), return
 * a sanitized list of symbols. Falls back to `[]` on any error
 * (corrupted JSON, wrong shape, non-string elements).
 */
export function parseRecent(raw: string | null): string[] {
  if (raw === null || raw === undefined) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const out: string[] = [];
  for (const item of parsed) {
    if (typeof item === 'string') out.push(item);
  }
  return out;
}

/**
 * Pure dedupe-and-cap — given the current list + a new symbol, return
 * a new list with the symbol prepended, case-insensitive dedupe
 * (coerce to uppercase), and capped at `max` entries.
 *
 * Returns the original list unchanged if `symbol` fails
 * `isValidSymbol` after normalization.
 */
export function recordRecent(
  list: string[],
  symbol: string,
  max: number = DEFAULT_MAX_RECENT
): string[] {
  const normalized = symbol.trim().toUpperCase();
  if (!isValidSymbol(normalized)) return list.slice();
  const filtered = list
    .map((s) => s.toUpperCase())
    .filter((s) => s !== normalized);
  return [normalized, ...filtered].slice(0, Math.max(0, max));
}

/**
 * Browser glue: read the recent list from localStorage.
 *
 * SSR-safe — returns `[]` when `window` is not available. Wrapped in
 * try/catch so privacy-mode / disabled-storage / quota errors don't
 * surface to the caller.
 */
export function readRecent(storageKey: string): string[] {
  if (typeof window === 'undefined') return [];
  try {
    return parseRecent(window.localStorage.getItem(storageKey));
  } catch {
    return [];
  }
}

/**
 * Browser glue: write the recent list to localStorage.
 *
 * SSR-safe + swallows errors (no-op when `window` is unavailable or
 * storage is full / blocked).
 */
export function writeRecent(storageKey: string, list: string[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(list));
  } catch {
    // ignore — quota, disabled storage, etc.
  }
}
