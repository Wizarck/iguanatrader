<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice trades-list-and-detail wires the trades table to the
   * already-shipped `GET /api/v1/trades` backend.
   */
  export const meta = {
    label: 'Trades',
    icon: 'arrow-up-right-from-square',
    order: 20
  } as const;
</script>

<script lang="ts">
  import { goto } from '$app/navigation';

  import Badge from '$lib/components/Badge.svelte';
  import DataTable, { type DataTableColumn } from '$lib/components/DataTable.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import type { TradeOut } from '$lib/trades/types';
  import { sideVariant, stateVariant } from '$lib/trades/variants';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  function handleRowClick(row: TradeOut): void {
    void goto(`/trades/${row.id}`);
  }
</script>

{#snippet sideCell(row: TradeOut)}
  <Badge label={row.side} variant={sideVariant(row.side)} />
{/snippet}

{#snippet stateCell(row: TradeOut)}
  <Badge label={row.state} variant={stateVariant(row.state)} />
{/snippet}

{#snippet closedCell(row: TradeOut)}
  {row.closed_at ?? '—'}
{/snippet}

<svelte:head>
  <title>Trades · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Trades</h1>

  {#if data.loadError}
    <div class="error" role="alert" data-testid="trades-load-error">
      {data.loadError}
    </div>
  {:else if data.trades.length === 0}
    <EmptyState
      title="No trades yet"
      body="Start the daemon to begin generating trades: `iguanatrader trading run --mode paper`."
      hint="See docs/mvp-deploy.md for the deployment flow."
    />
  {:else}
    <DataTable
      rows={data.trades}
      columns={[
        { key: 'symbol', header: 'Symbol' },
        { key: 'side', header: 'Side', cell: sideCell },
        { key: 'quantity', header: 'Qty' },
        { key: 'mode', header: 'Mode' },
        { key: 'state', header: 'State', cell: stateCell },
        { key: 'opened_at', header: 'Opened' },
        { key: 'closed_at', header: 'Closed', cell: closedCell }
      ] satisfies DataTableColumn<TradeOut>[]}
      rowKey={(t) => t.id}
      onRowClick={handleRowClick}
    />
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
