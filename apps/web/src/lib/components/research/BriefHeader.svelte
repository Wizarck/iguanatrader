<script lang="ts">
  // Slice research-frontend-extras §4.1 — header band of /research/[symbol].
  // Symbol + version + MethodologyBadge + synthesizedAt + Refresh CTA.
  //
  // v1 scope: read-only methodology (no edit dropdown), no stale-badge
  // logic (no per-methodology freshness threshold yet). Both deferred
  // to the post-Storybook research-frontend-extras-2 slice.

  import MethodologyBadge from './MethodologyBadge.svelte';

  type Props = {
    symbol: string;
    methodology: string;
    version: number;
    synthesizedAt: string | null; // ISO 8601 UTC
    refreshing: boolean;
    refreshError: string | null;
    onRefresh: () => Promise<void> | void;
  };

  let {
    symbol,
    methodology,
    version,
    synthesizedAt,
    refreshing,
    refreshError,
    onRefresh
  }: Props = $props();

  function formatTs(iso: string | null): string {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      return d.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
    } catch {
      return iso;
    }
  }
</script>

<header class="brief-header">
  <div class="left">
    <h1>{symbol}</h1>
    <span class="version" title="Brief version">v{version}</span>
    <MethodologyBadge {methodology} />
  </div>
  <div class="right">
    <div class="timestamps">
      <div class="ts-line">
        <span class="label">Synthesised:</span>
        <span class="value">{formatTs(synthesizedAt)}</span>
      </div>
    </div>
    <button type="button" onclick={() => onRefresh()} disabled={refreshing}>
      {#if refreshing}Synthesising…{:else}Refresh{/if}
    </button>
  </div>
</header>

{#if refreshError}
  <div class="error" role="alert">{refreshError}</div>
{/if}

<style>
  .brief-header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 16px 20px;
    background: var(--surface);
    border: 1px solid var(--mute);
    border-radius: 6px;
    margin-bottom: 16px;
  }
  .left {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  h1 {
    margin: 0;
    font-size: 22px;
    font-weight: 600;
    color: var(--ink);
  }
  .version {
    color: var(--mute);
    font-size: 14px;
    font-variant-numeric: tabular-nums;
  }
  .right {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .timestamps {
    display: flex;
    flex-direction: column;
    font-size: 12px;
    color: var(--mute);
  }
  .ts-line {
    display: flex;
    gap: 6px;
  }
  .label {
    font-weight: 500;
  }
  .value {
    font-variant-numeric: tabular-nums;
  }
  button {
    padding: 0.5rem 1rem;
    background: var(--accent);
    color: var(--accent-fg);
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
  }
  button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  .error {
    color: var(--err-fg, #c00);
    background: var(--err-bg, #fee);
    padding: 0.5rem 0.75rem;
    border-radius: 4px;
    margin-bottom: 12px;
  }
</style>
