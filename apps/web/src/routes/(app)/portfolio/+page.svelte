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
  import EmptyState from '$lib/components/EmptyState.svelte';
  import EquitySparkline from '$lib/components/EquitySparkline.svelte';
  import PortfolioSummary from '$lib/components/PortfolioSummary.svelte';
  import PositionsTable from '$lib/components/PositionsTable.svelte';
  import { resolveCurrencyCode } from '$lib/portfolio/format';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const currency = $derived(data.summary?.equity.currency ?? 'USD');
  // Which account these numbers belong to — paper (simulated) vs live (real
  // money) — so $1M of paper cash is never mistaken for real funds.
  const isPaperAccount = $derived((data.summary?.equity.mode ?? 'paper') !== 'live');
  const resolvedCurrency = $derived(resolveCurrencyCode(currency));
  const accountNote = $derived(
    `${isPaperAccount ? 'Simulated money' : 'Real money'} · ${resolvedCurrency}`
  );
  // Most recent broker-reconcile timestamp across positions — drives the
  // honesty caption that the real entry / unrealized P&L are point-in-time
  // (stamped each daemon reconcile), NOT a live feed.
  const marksSyncedAt = $derived(
    data.positions
      .map((p) => p.marks_updated_at)
      .filter((v): v is string => v !== null)
      .sort()
      .at(-1) ?? null
  );
  function formatSyncTime(iso: string): string {
    const d = new Date(iso);
    return Number.isNaN(d.getTime())
      ? iso
      : d.toLocaleString('en-US', {
          day: '2-digit',
          month: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        });
  }
  const isAllEmpty = $derived(
    data.summary !== null &&
      data.summary.equity.snapshot_kind === 'empty' &&
      data.positions.length === 0 &&
      data.equity_series.length === 0
  );
</script>

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
      title="No portfolio activity yet"
      body="Start the daemon: `iguanatrader trading run --mode paper`."
      hint="See docs/mvp-deploy.md for the deployment flow."
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

    <h2>Positions</h2>
    {#if data.positions.length === 0}
      <p class="muted" data-testid="positions-empty">No open positions.</p>
    {:else}
      <PositionsTable positions={data.positions} {currency} />
      {#if marksSyncedAt}
        <p class="sync-note" data-testid="marks-sync-note">
          Avg fill and unrealized P&L reconciled with IBKR · last sync
          {formatSyncTime(marksSyncedAt)} · not real-time
        </p>
      {/if}
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
  .sync-note {
    color: var(--mute);
    font-size: 12px;
    margin: 8px 0 0;
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
