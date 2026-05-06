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

<svelte:head>
  <title>Strategies · iguanatrader</title>
</svelte:head>

<section aria-busy="true" aria-live="polite">
  <h1>Strategies</h1>
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
