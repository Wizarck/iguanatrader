<script lang="ts">
  /**
   * Authenticated home — slice W1.
   *
   * The root `/` route under `(app)`. Slice 4 shipped a placeholder at
   * the root level (`/src/routes/+page.svelte`) which W1 retires in
   * favor of this gated home.
   *
   * For the W1 skeleton, the home renders a brief greeting + pointer to
   * the Sidebar. Slice T4 (`trading-routes-and-daemon`) replaces this
   * body with the dashboard summary widgets (equity sparkline, open
   * positions, today's PnL, etc. per j1.md §2).
   *
   * **Note**: this page intentionally does NOT export a `meta` const —
   * the Sidebar's `import.meta.glob` pattern targets
   * `(app)/<name>/+page.svelte` (subdirectory routes), NOT the bare
   * `(app)/+page.svelte` (root). The root has no Sidebar entry; users
   * land here via the brand mark / direct navigation to `/`.
   */
  import { page } from '$app/state';

  const user = $derived(page.data.user);
</script>

<svelte:head>
  <title>Dashboard · iguanatrader</title>
</svelte:head>

<section class="home" aria-labelledby="home-title">
  <h1 id="home-title">Welcome back</h1>
  {#if user}
    <p>
      Signed in as <strong>{user.email}</strong> · {user.role}
    </p>
  {/if}
  <p class="hint">
    Pick a domain from the sidebar. Each page replaces its
    <code>loading…</code> placeholder as the owning slice ships its
    content.
  </p>
</section>

<style>
  .home {
    color: var(--ink);
    max-width: 720px;
  }
  h1 {
    font-size: 24px;
    font-weight: 600;
    margin: 0 0 8px;
  }
  p {
    color: var(--mute);
    margin: 0 0 8px;
    line-height: 1.5;
  }
  strong {
    color: var(--ink);
  }
  code {
    font-family: var(--font-mono);
    background: var(--surface-2);
    padding: 1px 6px;
    border-radius: var(--r-1);
    color: var(--accent);
    font-size: 0.9em;
  }
  .hint {
    margin-top: 12px;
  }
</style>
