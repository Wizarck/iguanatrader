<script lang="ts">
  import { formatMoney } from '$lib/portfolio/format';
  import type { CostPerTradeDTO, CostSummaryDTO } from '$lib/costs/types';

  type Props = {
    summary: CostSummaryDTO;
    perTrade: CostPerTradeDTO;
  };

  let { summary, perTrade }: Props = $props();

  const costPerTradeDisplay = $derived(
    perTrade.cost_per_trade_usd === null
      ? '—'
      : formatMoney(perTrade.cost_per_trade_usd, 'USD'),
  );
</script>

<dl class="summary-card" data-testid="costs-summary-card">
  <div class="cell">
    <dt>Coste total</dt>
    <dd data-testid="summary-total-cost">{formatMoney(summary.total_cost_usd, 'USD')}</dd>
  </div>
  <div class="cell">
    <dt>Llamadas</dt>
    <dd data-testid="summary-calls">
      <span>{summary.total_calls}</span>
      <span class="calls-cached">({summary.cached_calls} cached)</span>
    </dd>
  </div>
  <div class="cell">
    <dt>Coste por trade</dt>
    <dd data-testid="summary-cost-per-trade">{costPerTradeDisplay}</dd>
  </div>
</dl>

<style>
  .summary-card {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
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
  .calls-cached {
    font-size: 13px;
    font-weight: 500;
    margin-left: 4px;
    color: var(--mute);
  }
  @media (max-width: 720px) {
    .summary-card {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
