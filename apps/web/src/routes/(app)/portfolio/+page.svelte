<script lang="ts">
  import { page } from '$app/state';

  // Stub portfolio page — slice W1 + slice T4 (trading-routes) layer
  // the actual portfolio rendering. Slice 4 lands this stub so the
  // login redirect-to flow has a concrete target.
  const user = $derived(page.data.user);
</script>

<svelte:head>
  <title>Portfolio · iguanatrader</title>
</svelte:head>

<main>
  <h1>Portfolio</h1>
  <p>Stub page. Real portfolio surface lands in slice T4 (trading-routes-and-daemon).</p>
  {#if user}
    <p>Signed in as <strong>{user.email}</strong> ({user.role}).</p>
  {/if}
</main>

<style>
  main {
    background: oklch(18% 0.02 250);
    color: oklch(95% 0.005 250);
    min-height: 100vh;
    padding: 32px;
    font-family:
      'Inter Variable',
      system-ui,
      -apple-system,
      'Segoe UI',
      sans-serif;
  }
  h1 {
    font-size: 24px;
    font-weight: 600;
    margin: 0 0 8px;
  }
  p {
    color: oklch(70% 0.012 250);
    margin: 0 0 12px;
  }
  strong {
    color: oklch(95% 0.005 250);
  }
</style>
