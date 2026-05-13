<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice P1 (`approval-channels-multichannel`) replaces the body.
   * `meta` stays.
   */
  export const meta = {
    label: 'Approvals',
    icon: 'bell',
    order: 50
  } as const;
</script>

<script lang="ts">
  import PlaceholderCard from '$lib/components/PlaceholderCard.svelte';
</script>

<svelte:head>
  <title>Approvals · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Approvals</h1>
  <PlaceholderCard
    apiPath="/api/v1/approvals + /api/v1/stream/approvals (SSE)"
    sliceRef="approval-channels-multichannel"
    hint="Cola HITL de proposals pendientes. Vacío hasta que el daemon trading genere proposals."
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
