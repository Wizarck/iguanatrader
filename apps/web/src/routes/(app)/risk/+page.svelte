<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice K1 (`risk-engine-protections`) replaces the body. `meta`
   * stays.
   */
  export const meta = {
    label: 'Risk',
    icon: 'gauge',
    order: 60
  } as const;
</script>

<script lang="ts">
  import PlaceholderCard from '$lib/components/PlaceholderCard.svelte';
</script>

<svelte:head>
  <title>Risk · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Risk</h1>
  <PlaceholderCard
    apiPath="/api/v1/risk/state"
    sliceRef="risk-engine-protections"
    hint="Estado del kill-switch + override history. UI completa con timeline aterriza en slice K1."
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
