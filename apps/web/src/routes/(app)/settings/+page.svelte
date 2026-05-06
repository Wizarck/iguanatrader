<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice R6 (`settings-and-secrets`) replaces the body. `meta` stays.
   */
  export const meta = {
    label: 'Settings',
    icon: 'settings',
    order: 80
  } as const;
</script>

<svelte:head>
  <title>Settings · iguanatrader</title>
</svelte:head>

<section aria-busy="true" aria-live="polite">
  <h1>Settings</h1>
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
