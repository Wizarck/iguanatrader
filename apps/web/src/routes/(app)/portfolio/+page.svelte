<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar
   * (`apps/web/src/lib/components/nav/Sidebar.svelte` via
   * `import.meta.glob('/src/routes/(app)/*/+page.svelte', { eager: true })`).
   *
   * Slice T4 (`trading-routes-and-daemon`) replaces the body of this
   * page with the J1 dashboard summary. The `meta` export STAYS — the
   * sidebar entry should not move when content lands.
   */
  export const meta = {
    label: 'Portfolio',
    icon: 'briefcase',
    order: 10
  } as const;
</script>

<svelte:head>
  <title>Portfolio · iguanatrader</title>
</svelte:head>

<section aria-busy="true" aria-live="polite">
  <h1>Portfolio</h1>
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
