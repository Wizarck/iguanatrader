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
  import SymbolSearchCard from '$lib/components/SymbolSearchCard.svelte';

  const STORAGE_KEY = 'iguanatrader.research.recent';
</script>

<svelte:head>
  <title>Research · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Research</h1>
  <p class="lead">
    Busca un symbol para abrir su brief sintetizado, o vuelve a uno reciente.
  </p>
  <SymbolSearchCard />
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
