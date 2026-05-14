<script lang="ts" module>
  // Route metadata — consumed by the dynamic Sidebar
  // (apps/web/src/lib/components/nav/Sidebar.svelte) via the
  // import.meta.glob anti-collision pattern (slice W1 design D2).
  export const meta = {
    label: 'Portfolio',
    icon: 'briefcase',
    order: 10
  } as const;
</script>

<script lang="ts">
  import Badge from '$lib/components/Badge.svelte';
  import DataTable, {
    type DataTableColumn
  } from '$lib/components/DataTable.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import EquitySparkline from '$lib/components/EquitySparkline.svelte';
  import PortfolioSummary from '$lib/components/PortfolioSummary.svelte';
  import { formatMoney } from '$lib/portfolio/format';
  import type { PositionOut } from '$lib/portfolio/types';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const currency = $derived(data.summary?.equity.currency ?? 'USD');
  const isAllEmpty = $derived(
    data.summary !== null &&
      data.summary.equity.snapshot_kind === 'empty' &&
      data.positions.length === 0 &&
      data.equity_series.length === 0
  );
</script>

{#snippet sideCell(row: PositionOut)}
  <Badge
    label={row.side}
    variant={row.side === 'buy' ? 'success' : 'destructive'}
  />
{/snippet}

{#snippet avgEntryCell(row: PositionOut)}
  {formatMoney(row.avg_entry_price, currency)}
{/snippet}

{#snippet lastPriceCell(row: PositionOut)}
  {formatMoney(row.last_price, currency)}
{/snippet}

{#snippet unrealizedCell(row: PositionOut)}
  {formatMoney(row.unrealized_pnl, currency)}
{/snippet}

<svelte:head>
  <title>Portfolio · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Portfolio</h1>

  {#if data.loadError}
    <div class="error" role="alert" data-testid="portfolio-load-error">
      {data.loadError}
    </div>
  {:else if isAllEmpty}
    <EmptyState
      title="No portfolio activity aún"
      body="Arranca el daemon: `iguanatrader trading run --mode paper`."
      hint="Consulta docs/mvp-deploy.md para el detalle del flujo de despliegue."
    />
  {:else if data.summary}
    <div class="overview">
      <div class="overview-summary">
        <PortfolioSummary
          totalValue={data.summary.equity.account_equity}
          dayPnlAbs={data.summary.day_pnl_abs}
          dayPnlPct={data.summary.day_pnl_pct}
          cash={data.summary.equity.cash_balance}
          positionCount={data.positions.length}
          {currency}
        />
      </div>
      <div class="overview-sparkline" data-testid="sparkline-wrapper">
        <EquitySparkline snapshots={data.equity_series} {currency} />
      </div>
    </div>

    <h2>Posiciones</h2>
    {#if data.positions.length === 0}
      <p class="muted" data-testid="positions-empty">Sin posiciones abiertas.</p>
    {:else}
      <DataTable
        rows={data.positions}
        columns={[
          { key: 'symbol', header: 'Symbol' },
          { key: 'side', header: 'Side', cell: sideCell },
          { key: 'quantity', header: 'Qty' },
          { key: 'avg_entry_price', header: 'Avg entry', cell: avgEntryCell },
          { key: 'last_price', header: 'Last', cell: lastPriceCell },
          {
            key: 'unrealized_pnl',
            header: 'Unrealized P&L',
            cell: unrealizedCell
          },
          { key: 'opened_at', header: 'Opened' }
        ] satisfies DataTableColumn<PositionOut>[]}
        rowKey={(p) => p.trade_id}
      />
    {/if}
  {/if}
</section>

<style>
  section {
    color: var(--ink);
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 16px;
  }
  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 24px 0 12px;
    color: var(--ink);
  }
  .overview {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 16px;
    align-items: center;
  }
  .overview-summary {
    min-width: 0;
  }
  .overview-sparkline {
    padding: 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
  }
  .muted {
    color: var(--mute);
    font-size: 14px;
    margin: 0;
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
  @media (max-width: 720px) {
    .overview {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
