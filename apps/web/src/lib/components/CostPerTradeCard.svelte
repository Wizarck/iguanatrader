<script lang="ts">
  import { costPerTradeColour } from '$lib/costs/format';
  import type { CostPerTradeDTO } from '$lib/costs/types';
  import { formatMoney } from '$lib/portfolio/format';

  type Props = {
    perTrade: CostPerTradeDTO;
  };

  let { perTrade }: Props = $props();

  const numericValue = $derived(
    perTrade.cost_per_trade_usd === null ? null : Number(perTrade.cost_per_trade_usd),
  );
  const tier = $derived(costPerTradeColour(numericValue));
  const bigNumber = $derived(
    perTrade.cost_per_trade_usd === null
      ? '—'
      : formatMoney(perTrade.cost_per_trade_usd, 'USD'),
  );
  const isNull = $derived(perTrade.cost_per_trade_usd === null);
</script>

<article
  class="cpt-card tier-{tier}"
  data-testid="cost-per-trade-card"
  data-tier={tier}
  aria-labelledby="cpt-label"
>
  <p id="cpt-label" class="label">Cost per trade</p>
  <p class="big-number" data-testid="cpt-big-number">{bigNumber}</p>
  {#if isNull}
    <p class="subtitle" data-testid="cpt-subtitle">No closed trades yet</p>
  {:else}
    <p class="subtitle" data-testid="cpt-subtitle">
      = {formatMoney(perTrade.total_llm_cost_usd, 'USD')} / {perTrade.closed_trades_count}
    </p>
  {/if}
</article>

<style>
  .cpt-card {
    padding: 20px 24px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    max-width: 360px;
  }
  .label {
    margin: 0 0 8px;
    color: var(--mute);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .big-number {
    margin: 0;
    color: var(--ink);
    font-size: 32px;
    font-weight: 700;
    line-height: 1.1;
  }
  .subtitle {
    margin: 8px 0 0;
    color: var(--mute);
    font-size: 13px;
    line-height: 1.45;
  }
  .tier-success {
    border-color: var(--success);
  }
  .tier-success .big-number {
    color: var(--success);
  }
  .tier-accent {
    border-color: var(--accent);
  }
  .tier-accent .big-number {
    color: var(--accent);
  }
  .tier-destructive {
    border-color: var(--destructive);
  }
  .tier-destructive .big-number {
    color: var(--destructive);
  }
</style>
