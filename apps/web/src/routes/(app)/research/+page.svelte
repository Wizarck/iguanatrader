<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice R5 (`research-brief-synthesis`) replaces the body. `meta`
   * stays.
   */
  export const meta = {
    label: 'Research',
    icon: 'search',
    order: 40
  } as const;
</script>

<script lang="ts">
  import PlaceholderCard from '$lib/components/PlaceholderCard.svelte';
</script>

<svelte:head>
  <title>Research · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Research</h1>
  <PlaceholderCard
    apiPath="/api/v1/research/briefs/{'{symbol}'}"
    sliceRef="research-brief-synthesis"
    hint="Watchlist + briefs sintetizados. Requiere ANTHROPIC_API_KEY + claves Tier-A para generar briefs reales."
  />
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
</style>
