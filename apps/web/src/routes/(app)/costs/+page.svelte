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

<svelte:head>
  <title>Costs · iguanatrader</title>
</svelte:head>

<section aria-busy="true" aria-live="polite">
  <h1>Costs</h1>
  <p>loading…</p>
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
  p {
    color: var(--mute);
    margin: 0;
  }
</style>
