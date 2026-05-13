<script lang="ts">
  /**
   * Honest empty-state card for dashboard tabs whose UI has not landed
   * yet. Replaces the previous static ``loading…`` text which lied
   * about a non-existent loading state. Each consumer page picks a
   * label, the backend route name (so a power-user can hit it via
   * `/docs`), and the future slice name responsible for shipping real
   * content.
   */

  type Props = {
    /** Card heading (defaults to "Vista pendiente"). */
    title?: string;
    /** Backend route path the data will eventually surface from. */
    apiPath: string;
    /** Future slice name that will land the real UI. */
    sliceRef: string;
    /** Optional extra hint (e.g., "requires ANTHROPIC_API_KEY"). */
    hint?: string;
  };

  let {
    title = 'Vista pendiente',
    apiPath,
    sliceRef,
    hint
  }: Props = $props();
</script>

<div class="placeholder-card" data-testid="placeholder-card">
  <p class="placeholder-title">{title}</p>
  <p class="placeholder-detail">
    Backend disponible en <code>{apiPath}</code>. La UI aterriza en una
    slice futura (<code>{sliceRef}</code>).{#if hint}{' '}{hint}{/if}
  </p>
</div>

<style>
  .placeholder-card {
    margin-top: 16px;
    padding: 16px 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    max-width: 640px;
  }
  .placeholder-title {
    margin: 0 0 8px;
    color: var(--ink);
    font-size: 15px;
    font-weight: 600;
  }
  .placeholder-detail {
    margin: 0;
    color: var(--mute);
    font-size: 14px;
    line-height: 1.5;
  }
  code {
    color: var(--accent);
    font-family: var(--font-mono);
    font-size: 12px;
    padding: 0 4px;
  }
</style>
