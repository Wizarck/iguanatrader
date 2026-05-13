<script lang="ts" module>
  // Route metadata — consumed by the dynamic Sidebar
  // (apps/web/src/lib/components/nav/Sidebar.svelte) via the
  // import.meta.glob anti-collision pattern (slice W1 design D2).
  //
  // Slice T4 (trading-routes-and-daemon) replaces the body of this
  // page with the J1 dashboard summary. The meta export STAYS — the
  // sidebar entry should not move when content lands.
  export const meta = {
    label: 'Portfolio',
    icon: 'briefcase',
    order: 10
  } as const;
</script>

<script lang="ts">
  import PlaceholderCard from '$lib/components/PlaceholderCard.svelte';
</script>

<svelte:head>
  <title>Portfolio · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Portfolio</h1>
  <PlaceholderCard
    apiPath="/api/v1/portfolio"
    sliceRef="trading-routes-and-daemon"
    hint="Mostrará cash + positions + equity curve cuando la slice T4 wireée la UI."
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
