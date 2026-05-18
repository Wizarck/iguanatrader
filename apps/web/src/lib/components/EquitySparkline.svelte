<script lang="ts">
  import { buildSparklinePath } from '$lib/portfolio/sparkline';
  import type { EquitySnapshotOut } from '$lib/portfolio/types';

  type Props = {
    snapshots: EquitySnapshotOut[];
    width?: number;
    height?: number;
    currency?: string;
  };

  let {
    snapshots,
    width = 240,
    height = 72,
    currency = 'USD'
  }: Props = $props();

  // Number() conversion is plot-only precision (bounded equity values,
  // ~240-pixel canvas) — never used for user-facing money math.
  const values = $derived(snapshots.map((s) => Number(s.account_equity)));
  const path = $derived(buildSparklinePath(values, width, height));

  const firstEquity = $derived(snapshots[0]?.account_equity ?? null);
  const lastEquity = $derived(
    snapshots[snapshots.length - 1]?.account_equity ?? null
  );
  const trend = $derived(deriveTrend(values));
  const ariaLabel = $derived(
    snapshots.length === 0
      ? 'No equity data'
      : snapshots.length === 1
        ? `Equity flat at ${firstEquity} ${currency}`
        : `Equity ${trend} between ${firstEquity} and ${lastEquity} ${currency} (${snapshots.length} points)`
  );

  function deriveTrend(xs: number[]): string {
    if (xs.length < 2) return 'flat';
    const delta = xs[xs.length - 1] - xs[0];
    if (delta > 0) return 'rising';
    if (delta < 0) return 'falling';
    return 'flat';
  }
</script>

{#if snapshots.length === 0}
  <p class="sparkline-empty" data-testid="sparkline-empty">No data yet</p>
{:else}
  <svg
    class="sparkline"
    data-testid="equity-sparkline"
    {width}
    {height}
    viewBox="0 0 {width} {height}"
    role="img"
    aria-label={ariaLabel}
  >
    <title>{ariaLabel}</title>
    <path
      d={path}
      fill="none"
      stroke="var(--accent)"
      stroke-width="1.5"
      stroke-linejoin="round"
      stroke-linecap="round"
    />
  </svg>
{/if}

<style>
  .sparkline {
    display: block;
    color: var(--accent);
  }
  .sparkline-empty {
    margin: 0;
    color: var(--mute);
    font-size: 13px;
    font-style: italic;
  }
</style>
