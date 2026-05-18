<script lang="ts" module>
  /**
   * Autocompleting symbol search (slice U1).
   *
   * Debounced prefix lookup against `GET /api/v1/symbols/search` —
   * drops a dropdown of matching tenant-universe rows so the operator
   * can pick by ticker + sector instead of typing a remembered string.
   *
   * Behaviour:
   *   - 150 ms debounce on input changes (key bursts collapse into one fetch).
   *   - Keyboard navigation: ↓/↑ move highlight, Enter selects, Esc closes.
   *   - "+ Research [Q]" trailing entry when the typed prefix doesn't
   *     match anything registered — leverages the ad-hoc auto-register
   *     flow already shipped in PR #214 so the operator can still
   *     onboard a brand-new ticker in one click.
   */
  export type SymbolMatch = {
    symbol: string;
    name: string | null;
    exchange: string | null;
    sector: string | null;
    industry: string | null;
    registered: boolean;
  };
</script>

<script lang="ts">
  import { goto } from '$app/navigation';

  import { isValidSymbol } from '$lib/research/recent';

  type Props = {
    onSelect?: (symbol: string) => void;
    initialValue?: string;
  };

  let { onSelect, initialValue = '' }: Props = $props();

  let value = $state(initialValue);
  let matches = $state<SymbolMatch[]>([]);
  let highlight = $state<number>(-1);
  let open = $state(false);
  let loading = $state(false);
  let error = $state<string | null>(null);

  // Increment on every keypress; pending requests check this to discard
  // stale responses (latest-wins).
  let requestSeq = 0;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function scheduleSearch(q: string): void {
    if (debounceTimer !== null) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => void runSearch(q), 150);
  }

  async function runSearch(q: string): Promise<void> {
    const seq = ++requestSeq;
    loading = true;
    try {
      const url = `/api/v1/symbols/search?q=${encodeURIComponent(q)}&limit=10`;
      const res = await fetch(url, { credentials: 'include' });
      if (seq !== requestSeq) return; // stale — newer search has fired
      if (!res.ok) {
        matches = [];
        return;
      }
      matches = (await res.json()) as SymbolMatch[];
      highlight = matches.length > 0 ? 0 : -1;
    } catch (e) {
      // Network error — treat as "no matches", quiet degradation.
      if (seq === requestSeq) matches = [];
    } finally {
      if (seq === requestSeq) loading = false;
    }
  }

  function onInput(event: Event): void {
    const target = event.target as HTMLInputElement;
    value = target.value;
    open = value.length > 0;
    error = null;
    if (open) {
      scheduleSearch(value);
    } else {
      matches = [];
    }
  }

  function commit(symbol: string): void {
    const normalized = symbol.trim().toUpperCase();
    if (!isValidSymbol(normalized)) {
      error = 'Invalid symbol — use 1-16 characters, A-Z and digits.';
      return;
    }
    open = false;
    matches = [];
    if (onSelect) {
      onSelect(normalized);
    } else {
      void goto(`/research/${encodeURIComponent(normalized)}`);
    }
  }

  function onKeyDown(event: KeyboardEvent): void {
    if (!open) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      const total = matches.length + 1; // +1 for the "+ Research" fallback row
      highlight = (highlight + 1) % total;
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      const total = matches.length + 1;
      highlight = (highlight - 1 + total) % total;
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (highlight >= 0 && highlight < matches.length) {
        commit(matches[highlight].symbol);
      } else {
        // Fallback row or no highlight → just submit the typed value.
        commit(value);
      }
    } else if (event.key === 'Escape') {
      open = false;
    }
  }

  function onBlur(): void {
    // Delay closing so a mouseup on a dropdown item still registers.
    setTimeout(() => {
      open = false;
    }, 120);
  }

  function onFocus(): void {
    if (value.length > 0) {
      open = true;
      if (matches.length === 0) void runSearch(value);
    }
  }

  // Are any of the current matches the exact typed string? If so we
  // suppress the "+ Research" fallback row to avoid a confusing duplicate.
  let typedAlreadyMatched = $derived(
    matches.some((m) => m.symbol === value.trim().toUpperCase())
  );

  let showFallbackRow = $derived(
    value.trim().length > 0 && isValidSymbol(value.trim().toUpperCase()) && !typedAlreadyMatched
  );
</script>

<div class="symbol-search">
  <input
    type="text"
    class="symbol-input"
    role="combobox"
    bind:value
    oninput={onInput}
    onkeydown={onKeyDown}
    onblur={onBlur}
    onfocus={onFocus}
    placeholder="Type a ticker — e.g. NVDA, AAPL, AMD"
    autocomplete="off"
    aria-label="Symbol search"
    aria-controls="symbol-search-listbox"
    aria-expanded={open}
    aria-haspopup="listbox"
    data-testid="symbol-search-input"
  />
  {#if open && (matches.length > 0 || showFallbackRow || loading)}
    <ul
      id="symbol-search-listbox"
      class="dropdown"
      role="listbox"
      data-testid="symbol-search-dropdown"
    >
      {#if loading && matches.length === 0}
        <li class="hint" aria-hidden="true">Searching…</li>
      {/if}
      {#each matches as match, idx (match.symbol)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
        <li
          class="row"
          class:highlighted={idx === highlight}
          role="option"
          aria-selected={idx === highlight}
          onmousedown={() => commit(match.symbol)}
        >
          <span class="symbol">{match.symbol}</span>
          {#if match.name}<span class="meta">{match.name}</span>{/if}
        </li>
      {/each}
      {#if showFallbackRow}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
        <li
          class="row fallback"
          class:highlighted={highlight === matches.length}
          role="option"
          aria-selected={highlight === matches.length}
          onmousedown={() => commit(value)}
        >
          <span class="symbol">+ Research {value.trim().toUpperCase()}</span>
          <span class="meta">Brand-new — will auto-register on refresh.</span>
        </li>
      {/if}
    </ul>
  {/if}
  {#if error}
    <p class="error" role="alert">{error}</p>
  {/if}
</div>

<style>
  .symbol-search {
    position: relative;
    max-width: 480px;
  }
  .symbol-input {
    width: 100%;
    padding: 10px 12px;
    background: var(--surface);
    color: var(--ink);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    font-family: inherit;
    font-size: 15px;
  }
  .symbol-input:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  .dropdown {
    position: absolute;
    z-index: 5;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    margin: 0;
    padding: 4px 0;
    background: var(--surface);
    color: var(--ink);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    list-style: none;
    max-height: 280px;
    overflow-y: auto;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  }
  .row {
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 8px 12px;
    cursor: pointer;
    font-size: 13px;
  }
  .row.highlighted,
  .row:hover {
    background: var(--surface-hover, rgba(255, 255, 255, 0.06));
  }
  .row .symbol {
    font-weight: 600;
    color: var(--ink);
    font-variant-numeric: tabular-nums;
  }
  .row .meta {
    color: var(--mute);
    font-size: 12px;
  }
  .row.fallback {
    border-top: 1px solid var(--border);
    margin-top: 2px;
    padding-top: 10px;
  }
  .row.fallback .symbol {
    color: var(--accent);
  }
  .hint {
    padding: 8px 12px;
    color: var(--mute);
    font-size: 12px;
  }
  .error {
    margin-top: 6px;
    color: var(--err-fg, #c00);
    font-size: 12px;
  }
</style>
