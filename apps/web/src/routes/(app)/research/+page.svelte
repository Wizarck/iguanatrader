<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice `research-tab-ui` replaces the `PlaceholderCard` body with a
   * search-card + recent-symbols landing. `meta` stays.
   */
  export const meta = {
    label: 'Research',
    icon: 'search',
    order: 40
  } as const;
</script>

<script lang="ts">
  import RecentSymbolsList from '$lib/components/RecentSymbolsList.svelte';
  import SymbolSearch from '$lib/components/research/SymbolSearch.svelte';

  const STORAGE_KEY = 'iguanatrader.research.recent';
</script>

<svelte:head>
  <title>Research · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Research</h1>
  <p class="lead">
    Look up any ticker to synthesise a brief, or pick one from the recent list.
    Brand-new symbols auto-register on the first refresh and the system pulls
    fundamentals + analyst ratings + ESG + a 13-month price window inline.
  </p>
  <SymbolSearch />
  <RecentSymbolsList storageKey={STORAGE_KEY} />
</section>

<style>
  section {
    color: var(--ink);
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 8px;
  }
  .lead {
    margin: 0 0 16px;
    color: var(--mute);
    font-size: 14px;
    line-height: 1.5;
    max-width: 640px;
  }
</style>
