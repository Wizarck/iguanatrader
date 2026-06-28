<script module lang="ts">
  export const meta = {
    label: 'Ingest runs',
    icon: 'search',
    order: 70
  } as const;
</script>

<script lang="ts">
  import Badge from '$lib/components/Badge.svelte';
  import DataTable, { type DataTableColumn } from '$lib/components/DataTable.svelte';
  import type { IngestRunOut } from '$lib/admin/types';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  function statusVariant(status: string): 'success' | 'destructive' | 'muted' | 'info' {
    switch (status) {
      case 'ok':
        return 'success';
      case 'error':
        return 'destructive';
      case 'started':
        return 'info';
      default:
        return 'muted';
    }
  }

  function fmtDuration(started: string, finished: string | null): string {
    if (!finished) return 'in-progress';
    try {
      const a = new Date(started).getTime();
      const b = new Date(finished).getTime();
      const seconds = Math.max(0, (b - a) / 1000);
      if (seconds < 60) return `${seconds.toFixed(1)}s`;
      return `${(seconds / 60).toFixed(1)}m`;
    } catch {
      return '—';
    }
  }
</script>

{#snippet statusCell(row: IngestRunOut)}
  <Badge label={row.status} variant={statusVariant(row.status)} />
{/snippet}

{#snippet symbolCell(row: IngestRunOut)}
  {row.symbol ?? '—'}
{/snippet}

{#snippet durationCell(row: IngestRunOut)}
  {fmtDuration(row.started_at, row.finished_at)}
{/snippet}

{#snippet errorCell(row: IngestRunOut)}
  {row.error_detail ?? '—'}
{/snippet}

<svelte:head>
  <title>Ingest runs · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <header class="page-header">
    <h1>Ingest scheduler history (I7)</h1>
    <p class="hint">
      Each row is an invocation of the <code>research_ingest</code> cron recorded by
      <code>IngestRunRecorder</code>. The scheduler runs daily at 06:00 UTC + Mon 06:00
      weekly per watchlist · source. Status <code>error</code> with detail usually means a
      missing env-var (<code>BEA_API_KEY</code>, <code>SEC_EDGAR_USER_AGENT</code>, etc.) —
      the ConfigError propagates here.
    </p>
    <nav class="filters">
      <a class:active={!data.statusFilter} href="/ingest-runs">All</a>
      <a class:active={data.statusFilter === 'ok'} href="/ingest-runs?status=ok">OK</a>
      <a class:active={data.statusFilter === 'error'} href="/ingest-runs?status=error">Errors</a>
      <a class:active={data.statusFilter === 'started'} href="/ingest-runs?status=started">In progress</a>
    </nav>
  </header>

  {#if data.loadError}
    <div class="error" role="alert">{data.loadError}</div>
  {:else if data.runs.length === 0}
    <p class="empty">
      No ingest runs yet
      {#if data.statusFilter}
        with status <code>{data.statusFilter}</code>
      {/if}. The cron's first tick is 06:00 UTC tomorrow, Mon-Fri.
    </p>
  {:else}
    <DataTable
      rows={data.runs}
      columns={[
        { key: 'started_at', header: 'Started' },
        { key: 'source_id', header: 'Source' },
        { key: 'symbol', header: 'Symbol', cell: symbolCell },
        { key: 'invoked_by', header: 'Invoked by' },
        { key: 'status', header: 'Status', cell: statusCell },
        { key: 'facts_inserted', header: 'Facts' },
        { key: 'duration', header: 'Duration', cell: durationCell },
        { key: 'error_detail', header: 'Error', cell: errorCell }
      ] satisfies DataTableColumn<IngestRunOut>[]}
      rowKey={(r) => r.id}
    />
  {/if}
</section>

<style>
  section {
    color: var(--ink);
  }
  .page-header { margin-bottom: 16px; }
  .page-header h1 { font-size: 22px; font-weight: 600; margin: 0 0 8px; }
  .page-header .hint {
    margin: 0;
    color: var(--mute);
    font-size: 13px;
    line-height: 1.5;
    max-width: 760px;
  }
  .page-header code {
    background: oklch(98% 0.01 240 / 0.04);
    padding: 1px 4px;
    border-radius: 3px;
    color: var(--accent);
    font-size: 12px;
  }
  .filters {
    display: flex;
    gap: 16px;
    margin-top: 12px;
    font-size: 13px;
  }
  .filters a {
    color: var(--mute);
    text-decoration: none;
    padding: 4px 8px;
    border-radius: 4px;
  }
  .filters a:hover { color: var(--ink); }
  .filters a.active {
    background: oklch(70% 0.18 220 / 0.14);
    color: var(--accent);
  }
  .empty {
    color: var(--mute);
    font-style: italic;
    margin-top: 24px;
  }
  .empty code {
    background: oklch(98% 0.01 240 / 0.04);
    padding: 1px 4px;
    border-radius: 3px;
    color: var(--accent);
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
