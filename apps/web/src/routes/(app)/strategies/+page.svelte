<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice T4 (`trading-routes-and-daemon`) replaces the body with
   * strategy management. `meta` stays.
   */
  export const meta = {
    label: 'Strategies',
    icon: 'cpu',
    order: 30
  } as const;
</script>

<script lang="ts">
  import PlaceholderCard from '$lib/components/PlaceholderCard.svelte';
</script>

<svelte:head>
  <title>Strategies · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Strategies</h1>
  <PlaceholderCard
    apiPath="/api/v1/strategies"
    sliceRef="trading-routes-and-daemon"
    hint="Listado + configuración de strategies (Donchian MVP + futuras)."
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
