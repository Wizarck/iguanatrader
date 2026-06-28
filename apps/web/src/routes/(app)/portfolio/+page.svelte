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
  import { formatMoney, resolveCurrencyCode } from '$lib/portfolio/format';
  import type { PositionOut } from '$lib/portfolio/types';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const currency = $derived(data.summary?.equity.currency ?? 'USD');
  // Which account these numbers belong to — paper (simulated) vs live (real
  // money) — so $1M of paper cash is never mistaken for real funds.
  const isPaperAccount = $derived((data.summary?.equity.mode ?? 'paper') !== 'live');
  const resolvedCurrency = $derived(resolveCurrencyCode(currency));
  const accountNote = $derived(
    `${isPaperAccount ? 'dinero simulado' : 'dinero real'} · ${resolvedCurrency}`
  );
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

{#snippet strategyCell(row: PositionOut)}
  {row.strategy_kind ?? '—'}
{/snippet}

{#snippet plannedEntryCell(row: PositionOut)}
  {formatMoney(row.entry_price_indicative, currency)}
{/snippet}

{#snippet avgEntryCell(row: PositionOut)}
  {#if row.avg_entry_price === null}
    <Badge label="pendiente de ejecución" variant="mute" />
  {:else}
    {formatMoney(row.avg_entry_price, currency)}
  {/if}
{/snippet}

{#snippet stopCell(row: PositionOut)}
  {formatMoney(row.stop_price, currency)}
{/snippet}

{#snippet targetCell(row: PositionOut)}
  {formatMoney(row.target_price, currency)}
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
    <div class="account-badge" data-testid="account-badge">
      <Badge
        label={isPaperAccount ? 'PAPER' : 'REAL'}
        variant={isPaperAccount ? 'warning' : 'destructive'}
      />
      <span class="account-note">{accountNote}</span>
    </div>
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
          { key: 'strategy_kind', header: 'Estrategia', cell: strategyCell },
          { key: 'quantity', header: 'Qty' },
          {
            key: 'entry_price_indicative',
            header: 'Entrada prev.',
            cell: plannedEntryCell
          },
          { key: 'avg_entry_price', header: 'Entrada real', cell: avgEntryCell },
          { key: 'stop_price', header: 'Stop', cell: stopCell },
          { key: 'target_price', header: 'Objetivo', cell: targetCell },
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
  .account-badge {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 16px;
  }
  .account-note {
    color: var(--mute);
    font-size: 13px;
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
