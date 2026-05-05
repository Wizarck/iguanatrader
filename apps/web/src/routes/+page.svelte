<script lang="ts">
  // Root `/` placeholder. Slice W1 mounts the dashboard skeleton here
  // (and brings it under the `(app)` route group so the cookie hook
  // gates it). For slice 4 this is just a marker page so SvelteKit
  // doesn't 404 on the root.
</script>

<main>
  <h1>iguanatrader</h1>
  <p>This is the iguanatrader root. The dashboard lands in slice W1.</p>
  <p>To sign in, visit <a href="/login">/login</a>.</p>
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
  a {
    color: oklch(72% 0.14 195);
  }
</style>
