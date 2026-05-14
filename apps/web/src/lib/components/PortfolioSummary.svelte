<script lang="ts">
  import { formatMoney, formatPercent } from '$lib/portfolio/format';

  type Props = {
    totalValue: string;
    dayPnlAbs: string | null;
    dayPnlPct: string | null;
    cash: string;
    positionCount: number;
    currency: string;
  };

  let {
    totalValue,
    dayPnlAbs,
    dayPnlPct,
    cash,
    positionCount,
    currency
  }: Props = $props();

  const pnlNumeric = $derived(dayPnlAbs === null ? null : Number(dayPnlAbs));
  const pnlSignClass = $derived(
    pnlNumeric === null || !Number.isFinite(pnlNumeric)
      ? ''
      : pnlNumeric >= 0
        ? 'pnl-positive'
        : 'pnl-negative'
  );
</script>

<dl class="summary-card" data-testid="portfolio-summary">
  <div class="cell">
    <dt>Total value</dt>
    <dd data-testid="summary-total">{formatMoney(totalValue, currency)}</dd>
  </div>
  <div class="cell">
    <dt>Day P&amp;L</dt>
    <dd class={pnlSignClass} data-testid="summary-day-pnl">
      {#if dayPnlAbs === null && dayPnlPct === null}
        —
      {:else}
        <span>{formatMoney(dayPnlAbs, currency)}</span>
        <span class="pnl-pct">({formatPercent(dayPnlPct)})</span>
      {/if}
    </dd>
  </div>
  <div class="cell">
    <dt>Cash</dt>
    <dd data-testid="summary-cash">{formatMoney(cash, currency)}</dd>
  </div>
  <div class="cell">
    <dt>Positions</dt>
    <dd data-testid="summary-positions">{positionCount}</dd>
  </div>
</dl>

<style>
  .summary-card {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 16px;
    margin: 0;
    padding: 16px 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
  }
  .cell {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  dt {
    color: var(--mute);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  dd {
    margin: 0;
    color: var(--ink);
    font-size: 18px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pnl-pct {
    font-size: 13px;
    font-weight: 500;
    margin-left: 4px;
  }
  .pnl-positive {
    color: var(--success);
  }
  .pnl-negative {
    color: var(--destructive);
  }
  @media (max-width: 720px) {
    .summary-card {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
