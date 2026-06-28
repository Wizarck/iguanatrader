<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice costs-dashboard-ui replaces the body. `meta` stays.
   */
  export const meta = {
    label: 'Costs',
    icon: 'wallet',
    order: 70
  } as const;
</script>

<script lang="ts">
  import CostPerTradeCard from '$lib/components/CostPerTradeCard.svelte';
  import CostsSummaryCard from '$lib/components/CostsSummaryCard.svelte';
  import DataTable, {
    type DataTableColumn
  } from '$lib/components/DataTable.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import type { PerProviderBreakdown } from '$lib/costs/types';
  import { formatMoney } from '$lib/portfolio/format';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const periodLabel = $derived(formatPeriod(data.summary?.period_start ?? null));
  const isEmpty = $derived(data.summary !== null && data.summary.total_calls === 0);

  function formatPeriod(isoStart: string | null): string {
    if (isoStart === null) return '';
    const parsed = new Date(isoStart);
    if (Number.isNaN(parsed.valueOf())) return '';
    const raw = new Intl.DateTimeFormat('en-US', {
      month: 'long',
      year: 'numeric',
      timeZone: 'UTC'
    }).format(parsed);
    return raw.charAt(0).toUpperCase() + raw.slice(1);
  }
</script>

{#snippet costCell(row: PerProviderBreakdown)}
  {formatMoney(row.cost_usd, 'USD')}
{/snippet}

<svelte:head>
  <title>Costs · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <header class="page-header">
    <h1>Costs</h1>
    {#if periodLabel}
      <p class="period" data-testid="costs-period">{periodLabel}</p>
    {/if}
  </header>

  {#if data.loadError}
    <div class="error" role="alert" data-testid="costs-load-error">
      {data.loadError}
    </div>
  {:else if isEmpty}
    <EmptyState
      title="No cost recorded yet"
      body="Costs accumulate as LangGraph nodes and external APIs are invoked."
      hint="See docs/observability.md for cost-meter details."
    />
  {:else if data.summary && data.byProvider && data.perTrade}
    <div class="grid">
      <div class="grid-summary">
        <CostsSummaryCard summary={data.summary} perTrade={data.perTrade} />
      </div>
      <div class="grid-cpt">
        <CostPerTradeCard perTrade={data.perTrade} />
      </div>
    </div>

    <h2>Breakdown by provider</h2>
    {#if data.byProvider.breakdown.length === 0}
      <p class="muted" data-testid="by-provider-empty">No providers with recorded cost.</p>
    {:else}
      <DataTable
        rows={data.byProvider.breakdown}
        columns={[
          { key: 'provider', header: 'Provider' },
          { key: 'cost_usd', header: 'USD spent', cell: costCell },
          { key: 'call_count', header: 'Call count' }
        ] satisfies DataTableColumn<PerProviderBreakdown>[]}
        rowKey={(r) => r.provider}
      />
    {/if}
  {/if}
</section>

<style>
  section {
    color: var(--ink);
  }
  .page-header {
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin: 0 0 16px;
    flex-wrap: wrap;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0;
  }
  .period {
    margin: 0;
    color: var(--mute);
    font-size: 14px;
  }
  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 24px 0 12px;
    color: var(--ink);
  }
  .grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 16px;
    align-items: stretch;
  }
  .grid-summary {
    min-width: 0;
  }
  .grid-cpt {
    display: flex;
    align-items: stretch;
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
    .grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
