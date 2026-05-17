<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice strategies-config-ui wires the table to the 4 CRUD endpoints
   * shipped by PR #142.
   */
  export const meta = {
    label: 'Strategies',
    icon: 'cpu',
    order: 30,
  } as const;
</script>

<script lang="ts">
  import { goto, invalidateAll } from '$app/navigation';

  import Badge from '$lib/components/Badge.svelte';
  import DataTable, { type DataTableColumn } from '$lib/components/DataTable.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import type { StrategyConfigOut } from '$lib/strategies/types';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  let disableError = $state<string | null>(null);

  function handleRowClick(row: StrategyConfigOut): void {
    void goto(`/strategies/${row.symbol}`);
  }

  function handleEdit(event: MouseEvent, row: StrategyConfigOut): void {
    event.stopPropagation();
    void goto(`/strategies/${row.symbol}`);
  }

  async function handleDisable(event: MouseEvent, row: StrategyConfigOut): Promise<void> {
    event.stopPropagation();
    const confirmed = confirm(
      `Disable the strategy for ${row.symbol}? Config is preserved (soft-disable); it just stops generating signals.`,
    );
    if (!confirmed) return;
    disableError = null;
    try {
      const res = await fetch(`/strategies/${row.symbol}?/disable`, {
        method: 'POST',
        headers: { Accept: 'application/json' },
        body: new URLSearchParams({ symbol: row.symbol }),
      });
      if (!res.ok && res.status !== 303) {
        disableError = `Failed to disable ${row.symbol}: ${res.status} ${res.statusText}`;
        return;
      }
      await invalidateAll();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      disableError = `Failed to disable ${row.symbol}: ${message}`;
    }
  }
</script>

{#snippet enabledCell(row: StrategyConfigOut)}
  <Badge
    label={row.enabled ? 'enabled' : 'disabled'}
    variant={row.enabled ? 'success' : 'mute'}
  />
{/snippet}

{#snippet actionsCell(row: StrategyConfigOut)}
  <div class="actions">
    <button
      type="button"
      class="btn btn--ghost"
      data-testid="edit-{row.symbol}"
      onclick={(e) => handleEdit(e, row)}
    >
      Edit
    </button>
    {#if row.enabled}
      <button
        type="button"
        class="btn btn--danger"
        data-testid="disable-{row.symbol}"
        onclick={(e) => handleDisable(e, row)}
      >
        Disable
      </button>
    {/if}
  </div>
{/snippet}

<svelte:head>
  <title>Strategies · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <header class="page-header">
    <h1>Strategies</h1>
    <a class="btn btn--primary" href="/strategies/new" data-testid="new-strategy">
      New strategy
    </a>
  </header>

  {#if data.loadError}
    <div class="error" role="alert" data-testid="strategies-load-error">
      {data.loadError}
    </div>
  {:else if disableError}
    <div class="error" role="alert" data-testid="strategies-disable-error">
      {disableError}
    </div>
  {:else if data.strategies.length === 0}
    <EmptyState
      title="No strategies configured yet"
      body="Create one to start generating signals."
      hint="docs/strategies.md lists every available kind and its parameters."
    />
  {:else}
    <DataTable
      rows={data.strategies}
      columns={[
        { key: 'symbol', header: 'Symbol' },
        { key: 'strategy_kind', header: 'Strategy kind' },
        { key: 'enabled', header: 'Enabled', cell: enabledCell },
        { key: 'version', header: 'Version' },
        { key: 'updated_at', header: 'Updated' },
        { key: 'actions', header: 'Actions', cell: actionsCell },
      ] satisfies DataTableColumn<StrategyConfigOut>[]}
      rowKey={(s) => s.id}
      onRowClick={handleRowClick}
    />
  {/if}
</section>

<style>
  section {
    color: var(--ink);
  }
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin: 0 0 16px;
    gap: 12px;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0;
  }
  .btn {
    display: inline-block;
    padding: 8px 14px;
    border-radius: var(--r-2);
    font-family: inherit;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    text-decoration: none;
    line-height: 1.4;
  }
  .btn--primary {
    background: var(--accent);
    color: var(--accent-fg);
  }
  .btn--primary:hover {
    background: var(--accent-hover);
  }
  .btn--ghost {
    background: transparent;
    color: var(--ink);
    border-color: var(--border);
  }
  .btn--ghost:hover {
    background: var(--surface-2);
  }
  .btn--danger {
    background: transparent;
    color: var(--destructive);
    border-color: oklch(64% 0.2 25 / 0.5);
  }
  .btn--danger:hover {
    background: oklch(64% 0.2 25 / 0.12);
  }
  .actions {
    display: inline-flex;
    gap: 8px;
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
