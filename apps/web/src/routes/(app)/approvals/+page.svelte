<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice `approvals-dashboard-ui` (PR #146) wires the body to the
   * pending-list + approve/reject endpoints shipped by slice P1.
   */
  export const meta = {
    label: 'Approvals',
    icon: 'bell',
    order: 50,
  } as const;
</script>

<script lang="ts">
  import ApprovalCard from '$lib/components/ApprovalCard.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';

  import type { ActionData, PageData } from './$types';

  type FormShape = {
    formError?: string;
  };

  let { data, form }: { data: PageData; form?: ActionData } = $props();
  const formTyped = $derived(form as FormShape | undefined);

  const pendingCount = $derived(data.approvals.length);
  const countLabel = $derived(
    pendingCount === 1 ? '1 pendiente' : `${pendingCount} pendientes`,
  );
</script>

<svelte:head>
  <title>Approvals · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <header class="page-header">
    <h1>Approvals</h1>
    {#if pendingCount > 0}
      <Badge label={countLabel} variant="accent" />
    {/if}
  </header>

  {#if data.loadError}
    <div class="error" role="alert" data-testid="approvals-load-error">
      {data.loadError}
    </div>
  {:else}
    {#if formTyped?.formError}
      <div class="error" role="alert" data-testid="form-error">{formTyped.formError}</div>
    {/if}

    {#if data.approvals.length === 0}
      <EmptyState
        title="No pending approvals."
        body="No proposals in queue. When the trading daemon generates a proposal, it will appear here with its countdown."
        hint="You can also respond from Telegram or WhatsApp if your tenant has those channels configured."
      />
    {:else}
      <ul class="cards" data-testid="approvals-list">
        {#each data.approvals as approval (approval.id)}
          <li>
            <ApprovalCard {approval} />
          </li>
        {/each}
      </ul>
    {/if}
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
  .cards {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 12px;
    max-width: 720px;
  }
  .error {
    margin-top: 16px;
    margin-bottom: 16px;
    padding: 12px 16px;
    background: oklch(64% 0.2 25 / 0.14);
    border: 1px solid oklch(64% 0.2 25 / 0.4);
    border-radius: var(--r-2);
    color: var(--destructive);
    font-size: 14px;
  }
</style>
