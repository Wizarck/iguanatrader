<script module lang="ts">
  export const meta = {
    label: 'Proposals',
    icon: 'cpu',
    order: 35
  } as const;
</script>

<script lang="ts">
  import { goto } from '$app/navigation';
  import Badge from '$lib/components/Badge.svelte';
  import DataTable, { type DataTableColumn } from '$lib/components/DataTable.svelte';
  import type { ProposalOut } from '$lib/proposals/types';
  import { sideVariant } from '$lib/trades/variants';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  function handleRowClick(row: ProposalOut): void {
    void goto(`/proposals/${row.id}`);
  }
</script>

{#snippet sideCell(row: ProposalOut)}
  <Badge label={row.side} variant={sideVariant(row.side)} />
{/snippet}

{#snippet targetCell(row: ProposalOut)}
  {row.target_price ?? '—'}
{/snippet}

{#snippet confidenceCell(row: ProposalOut)}
  {row.confidence_score ?? '—'}
{/snippet}

<svelte:head>
  <title>Proposals · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <header class="page-header">
    <h1>Proposals</h1>
    <p class="hint">
      Lista de propuestas emitidas por las strategies. Cada propuesta lleva su
      <code>stop_price</code> y (cuando aplica) un <code>target_price</code> emitido por la
      LLM. Click en cualquier fila para abrir el detalle, ejecutar
      <code>explain_proposal</code> o lanzar el <code>risk_review</code>.
    </p>
  </header>

  {#if data.loadError}
    <div class="error" role="alert">{data.loadError}</div>
  {:else if data.proposals.length === 0}
    <p class="empty">No hay proposals todavía.</p>
  {:else}
    <DataTable
      rows={data.proposals}
      columns={[
        { key: 'created_at', header: 'Created' },
        { key: 'symbol', header: 'Symbol' },
        { key: 'side', header: 'Side', cell: sideCell },
        { key: 'quantity', header: 'Qty' },
        { key: 'entry_price_indicative', header: 'Entry' },
        { key: 'stop_price', header: 'Stop' },
        { key: 'target_price', header: 'Target', cell: targetCell },
        { key: 'confidence_score', header: 'Conf.', cell: confidenceCell },
        { key: 'mode', header: 'Mode' }
      ] satisfies DataTableColumn<ProposalOut>[]}
      rowKey={(p) => p.id}
      onRowClick={handleRowClick}
    />
  {/if}
</section>

<style>
  section {
    color: var(--ink);
  }
  .page-header {
    margin-bottom: 16px;
  }
  .page-header h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 8px;
  }
  .page-header .hint {
    margin: 0;
    color: var(--mute);
    font-size: 13px;
    line-height: 1.5;
    max-width: 720px;
  }
  .page-header code {
    background: oklch(98% 0.01 240 / 0.04);
    padding: 1px 4px;
    border-radius: 3px;
    color: var(--accent);
    font-size: 12px;
  }
  .empty {
    color: var(--mute);
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
