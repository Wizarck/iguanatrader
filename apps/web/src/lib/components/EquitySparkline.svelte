<script lang="ts">
  import { formatMoney, formatPercent } from '$lib/portfolio/format';
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
  // High / low of the plotted band — the path normalises max to the top edge
  // and min to the bottom edge, so these label what the line's full height
  // spans (answers "what are the axes?").
  const maxEquity = $derived(values.length ? String(Math.max(...values)) : null);
  const minEquity = $derived(values.length ? String(Math.min(...values)) : null);

  // Signed change over the window (last − first), with a percent when the
  // starting equity is non-zero. Drives the coloured Δ chip.
  const deltaAbs = $derived(
    firstEquity !== null && lastEquity !== null
      ? Number(lastEquity) - Number(firstEquity)
      : null
  );
  const deltaPct = $derived(
    deltaAbs !== null && firstEquity !== null && Number(firstEquity) !== 0
      ? deltaAbs / Number(firstEquity)
      : null
  );
  const deltaClass = $derived(
    deltaAbs === null || deltaAbs === 0
      ? 'flat'
      : deltaAbs > 0
        ? 'up'
        : 'down'
  );
  const deltaSign = $derived(deltaAbs !== null && deltaAbs > 0 ? '+' : '');

  const trend = $derived(deriveTrend(values));
  const ariaLabel = $derived(
    snapshots.length === 0
      ? 'No equity data'
      : snapshots.length === 1
        ? `Account equity flat at ${firstEquity} ${currency}`
        : `Account equity ${trend} from ${firstEquity} to ${lastEquity} ${currency} (${snapshots.length} points)`
  );

  function deriveTrend(xs: number[]): string {
    if (xs.length < 2) return 'flat';
    const delta = xs[xs.length - 1] - xs[0];
    if (delta > 0) return 'up';
    if (delta < 0) return 'down';
    return 'flat';
  }
</script>

{#if snapshots.length === 0}
  <p class="sparkline-empty" data-testid="sparkline-empty">No data yet</p>
{:else}
  <figure class="sparkline-fig" data-testid="equity-sparkline-figure">
    <figcaption class="caption">
      <span class="caption-title">Equity · last 30 days</span>
      <span class="caption-current" data-testid="sparkline-current">
        {formatMoney(lastEquity, currency)}
        <span class="delta delta--{deltaClass}" data-testid="sparkline-delta">
          {#if deltaAbs === null}
            —
          {:else}
            {deltaSign}{formatMoney(String(deltaAbs), currency)}{#if deltaPct !== null}<span
                class="delta-pct"
              >
                ({deltaSign}{formatPercent(String(deltaPct))})</span
              >{/if}
          {/if}
        </span>
      </span>
    </figcaption>

    <div class="plot">
      <svg
        class="sparkline"
        data-testid="equity-sparkline"
        {width}
        {height}
        viewBox="0 0 {width} {height}"
        role="img"
        aria-label={ariaLabel}
        preserveAspectRatio="none"
      >
        <title>{ariaLabel}</title>
        <!-- High / low guide rails: the path fills the full height, so the top
             edge is the window high and the bottom edge the window low. -->
        <line class="guide" x1="0" y1="1" x2={width} y2="1" />
        <line class="guide" x1="0" y1={height - 1} x2={width} y2={height - 1} />
        <path
          d={path}
          fill="none"
          stroke="var(--accent)"
          stroke-width="1.5"
          stroke-linejoin="round"
          stroke-linecap="round"
          vector-effect="non-scaling-stroke"
        />
      </svg>
      <div class="band" aria-hidden="true">
        <span class="band-hi" data-testid="sparkline-high"
          >{formatMoney(maxEquity, currency)}</span
        >
        <span class="band-lo" data-testid="sparkline-low"
          >{formatMoney(minEquity, currency)}</span
        >
      </div>
    </div>
  </figure>
{/if}

<style>
  .sparkline-fig {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .caption {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .caption-title {
    color: var(--mute);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .caption-current {
    color: var(--ink);
    font-size: 15px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .delta {
    font-size: 12px;
    font-weight: 500;
    margin-left: 4px;
  }
  .delta-pct {
    opacity: 0.85;
  }
  .delta--up {
    color: var(--success);
  }
  .delta--down {
    color: var(--destructive);
  }
  .delta--flat {
    color: var(--mute);
  }
  .plot {
    display: flex;
    align-items: stretch;
    gap: 8px;
  }
  .sparkline {
    display: block;
    color: var(--accent);
    flex: 0 0 auto;
  }
  .guide {
    stroke: var(--border);
    stroke-width: 1;
    stroke-dasharray: 2 3;
  }
  .band {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    color: var(--mute);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .band-lo {
    color: var(--mute);
  }
  .sparkline-empty {
    margin: 0;
    color: var(--mute);
    font-size: 13px;
    font-style: italic;
  }
</style>
