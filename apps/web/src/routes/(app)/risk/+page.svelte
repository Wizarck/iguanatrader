<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar
   * (apps/web/src/lib/components/nav/Sidebar.svelte) via the
   * import.meta.glob anti-collision pattern (slice W1 design D2).
   */
  export const meta = {
    label: 'Risk',
    icon: 'gauge',
    order: 60
  } as const;
</script>

<script lang="ts">
  import Badge from '$lib/components/Badge.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import RiskCapsCard from '$lib/components/RiskCapsCard.svelte';
  import RiskUtilisationCard from '$lib/components/RiskUtilisationCard.svelte';
  import { formatMoney } from '$lib/portfolio/format';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const isAllEmpty = $derived(
    data.risk !== null &&
      Object.values(data.risk.utilisation).every(
        (v) => v === '0' || Number(v) === 0
      ) &&
      data.risk.state.capital === '0' &&
      data.risk.state.open_positions_count === 0
  );
</script>

<svelte:head>
  <title>Risk · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <header class="page-header">
    <h1>Risk</h1>
    {#if data.risk}
      <Badge
        label={data.risk.kill_switch_active ? 'Kill-switch ACTIVO' : 'Operativo'}
        variant={data.risk.kill_switch_active ? 'destructive' : 'success'}
      />
    {/if}
  </header>

  {#if data.loadError}
    <div class="error" role="alert" data-testid="risk-load-error">
      {data.loadError}
    </div>
  {:else if data.risk && isAllEmpty}
    <EmptyState
      title="No risk activity yet"
      body="State will initialize once the daemon starts."
      hint="Start the daemon: `iguanatrader trading run --mode paper`."
    />
  {:else if data.risk}
    <h2>Caps</h2>
    <RiskCapsCard caps={data.risk.caps} />

    <h2>Utilisation</h2>
    <RiskUtilisationCard utilisation={data.risk.utilisation} caps={data.risk.caps} />

    <h2>State</h2>
    <dl class="state-card" data-testid="risk-state-card">
      <div class="cell">
        <dt>Capital</dt>
        <dd data-testid="state-capital">{formatMoney(data.risk.state.capital, 'USD')}</dd>
      </div>
      <div class="cell">
        <dt>Open positions</dt>
        <dd data-testid="state-open-positions">
          {data.risk.state.open_positions_count} / {data.risk.caps.max_open_positions}
        </dd>
      </div>
      <div class="cell">
        <dt>Last update</dt>
        <dd data-testid="state-fetched-at">{data.risk.fetched_at}</dd>
      </div>
    </dl>
  {/if}
</section>

<style>
  section {
    color: var(--ink);
  }
  .page-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 0 0 16px;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0;
  }
  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 24px 0 12px;
    color: var(--ink);
  }
  .state-card {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 16px;
    margin: 0;
    padding: 16px 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
  }
  .cell {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  dt {
    color: var(--mute);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  dd {
    margin: 0;
    color: var(--ink);
    font-size: 18px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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
    .state-card {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
