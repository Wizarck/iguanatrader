<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice O1 (`observability-cost-meter`) replaces the body. `meta`
   * stays.
   */
  export const meta = {
    label: 'Costs',
    icon: 'wallet',
    order: 70
  } as const;
</script>

<script lang="ts">
  import PlaceholderCard from '$lib/components/PlaceholderCard.svelte';
</script>

<svelte:head>
  <title>Costs · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Costs</h1>
  <PlaceholderCard
    apiPath="/api/v1/costs/summary + /by-provider + /per-trade"
    sliceRef="observability-cost-meter"
    hint="Gasto LLM + broker tracking. Vacío hasta que se hagan llamadas reales (FakeLLM en MVP no cuenta)."
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
