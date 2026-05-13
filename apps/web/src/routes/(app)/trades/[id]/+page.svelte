<script lang="ts">
  import Badge from '$lib/components/Badge.svelte';
  import DataTable, { type DataTableColumn } from '$lib/components/DataTable.svelte';
  import type { FillOut } from '$lib/trades/types';
  import { sideVariant, stateVariant } from '$lib/trades/variants';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const fillsColumns: DataTableColumn<FillOut>[] = [
    { key: 'filled_at', header: 'Filled at' },
    { key: 'quantity_filled', header: 'Qty' },
    { key: 'fill_price', header: 'Price' },
    { key: 'commission', header: 'Commission' },
    { key: 'broker_fill_id', header: 'Broker fill ID' }
  ];
</script>

<svelte:head>
  <title>Trade · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <p class="back">
    <a href="/trades" data-testid="trades-back-link">← Volver a trades</a>
  </p>

  <h1>Detalle del trade</h1>

  {#if data.loadError}
    <div class="error" role="alert" data-testid="trade-load-error">
      {data.loadError}
    </div>
  {:else if data.trade}
    <article class="summary" data-testid="trade-summary">
      <header class="summary-header">
        <h2 class="symbol">{data.trade.symbol}</h2>
        <Badge label={data.trade.side} variant={sideVariant(data.trade.side)} />
        <Badge label={data.trade.state} variant={stateVariant(data.trade.state)} />
      </header>
      <dl class="summary-grid">
        <dt>Quantity</dt>
        <dd>{data.trade.quantity}</dd>
        <dt>Mode</dt>
        <dd>{data.trade.mode}</dd>
        <dt>Opened</dt>
        <dd>{data.trade.opened_at}</dd>
        <dt>Closed</dt>
        <dd>{data.trade.closed_at ?? '—'}</dd>
        <dt>Trade ID</dt>
        <dd><code>{data.trade.id}</code></dd>
      </dl>
    </article>

    <h2 class="fills-heading">Fills</h2>
    {#if data.fills.length === 0}
      <p class="fills-empty" data-testid="fills-empty">Sin fills aún.</p>
    {:else}
      <DataTable
        rows={data.fills}
        columns={fillsColumns}
        rowKey={(f) => f.id}
      />
    {/if}
  {/if}
</section>

<style>
  section {
    color: var(--ink);
  }
  .back {
    margin: 0 0 12px;
  }
  .back a {
    color: var(--accent);
    font-size: 14px;
    text-decoration: none;
  }
  .back a:hover {
    text-decoration: underline;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 16px;
  }
  .summary {
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
    padding: 20px 24px;
    max-width: 720px;
  }
  .summary-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }
  .summary-header .symbol {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    color: var(--ink);
  }
  .summary-grid {
    display: grid;
    grid-template-columns: 140px 1fr;
    gap: 8px 16px;
    margin: 0;
    font-size: 14px;
  }
  .summary-grid dt {
    color: var(--mute);
    font-weight: 500;
  }
  .summary-grid dd {
    margin: 0;
    color: var(--ink);
  }
  .summary-grid code {
    color: var(--accent);
    font-family: var(--font-mono);
    font-size: 12px;
  }
  .fills-heading {
    font-size: 16px;
    font-weight: 600;
    margin: 24px 0 12px;
    color: var(--ink);
  }
  .fills-empty {
    margin: 0;
    color: var(--mute);
    font-size: 14px;
    font-style: italic;
  }
  .error {
    margin-top: 16px;
    padding: 12px 16px;
    background: oklch(64% 0.2 25 / 0.14);
    border: 1px solid oklch(64% 0.2 25 / 0.4);
    border-radius: var(--r-2);
    color: var(--destructive);
    font-size: 14px;
  }
</style>
