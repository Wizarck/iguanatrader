<script lang="ts">
  /**
   * Recent symbols list — slice `research-tab-ui`.
   *
   * Reads the recent-symbols list from localStorage on mount (SSR-safe
   * via `readRecent`) and renders each entry as a `Badge accent`-styled
   * `<a href>` pill. Native `<a>` keeps the pills focusable +
   * keyboard-navigable without extra JS (Lighthouse-friendly).
   *
   * When the list is empty (first-load operator, cleared cache, or
   * corrupted localStorage) renders an `EmptyState`.
   *
   * v1.5 may swap the localStorage read for a server-backed watchlist
   * fetch (`research-watchlist-endpoint`); the consumer surface stays
   * the same.
   */
  import EmptyState from './EmptyState.svelte';

  import { readRecent, DEFAULT_MAX_RECENT } from '$lib/research/recent';

  type Props = {
    storageKey: string;
    max?: number;
    label?: string;
  };

  let { storageKey, max = DEFAULT_MAX_RECENT, label = 'Recent searches' }: Props = $props();

  // Read once on mount. The store is single-writer (the detail page);
  // re-reading on every render isn't necessary for MVP.
  let symbols = $state<string[]>(readRecent(storageKey).slice(0, max));
</script>

<section class="recent-list" data-testid="recent-symbols-list" aria-label={label}>
  <h2 class="recent-title">{label}</h2>
  {#if symbols.length === 0}
    <EmptyState
      title="No recent searches"
      body="Start by searching for a symbol above so it appears here."
    />
  {:else}
    <ul class="pills">
      {#each symbols as symbol (symbol)}
        <li>
          <a class="pill" href="/research/{symbol}" data-testid="recent-pill">{symbol}</a>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .recent-list {
    margin-top: 24px;
  }
  .recent-title {
    margin: 0 0 12px;
    font-size: 14px;
    font-weight: 600;
    color: var(--mute);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .pills {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .pills li {
    display: inline-flex;
  }
  .pill {
    display: inline-block;
    padding: 4px 12px;
    border-radius: var(--r-pill);
    font-size: 13px;
    font-weight: 600;
    line-height: 1.4;
    letter-spacing: 0.02em;
    background: oklch(72% 0.14 195 / 0.18);
    color: var(--accent);
    border: 1px solid oklch(72% 0.14 195 / 0.4);
    text-decoration: none;
    font-family: var(--font-mono, ui-monospace, monospace);
  }
  .pill:hover {
    filter: brightness(1.12);
  }
  .pill:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
</style>
