<script lang="ts">
  import { enhance } from '$app/forms';

  import { formatCountdown } from '$lib/approvals/countdown';
  import type { ApprovalRequest } from '$lib/approvals/types';
  import Badge from '$lib/components/Badge.svelte';
  import Textarea from '$lib/components/forms/Textarea.svelte';

  type Props = {
    approval: ApprovalRequest;
    /** Optional override — tests inject a fixed `Date` to avoid wall-clock flakiness. */
    initialNow?: Date;
  };

  let { approval, initialNow }: Props = $props();

  // Live clock tick: re-renders the countdown derivation once per second.
  // The cleanup function returned by `$effect` clears the interval on
  // component unmount (or whenever the effect re-runs with a new approval).
  let now = $state<Date>(initialNow ?? new Date());

  $effect(() => {
    const id = setInterval(() => {
      now = new Date();
    }, 1000);
    return () => clearInterval(id);
  });

  const countdown = $derived(formatCountdown(approval.expires_at, now));
  const expired = $derived(countdown === 'Expired');

  const headingId = $derived(`approval-${approval.id}`);
  const proposalShort = $derived(approval.proposal_id.slice(0, 8));

  let showRejectForm = $state(false);
  let rejectReason = $state('');

  function toggleReject() {
    showRejectForm = !showRejectForm;
  }

  const deliveryFailures = $derived(approval.delivery_failures ?? []);

  /**
   * Extract a human-readable channel name from a delivery-failure dict.
   * The DTO shape is `dict[str, Any]` — backend conventionally writes
   * `{ "channel": "telegram", "error": "..." }`. We fall back to the
   * stringified blob if `channel` is absent so a malformed payload still
   * renders something rather than crashing the row.
   */
  function failureChannel(failure: Record<string, unknown>): string {
    const ch = failure.channel;
    if (typeof ch === 'string' && ch.length > 0) return ch;
    return JSON.stringify(failure);
  }
</script>

<article
  class="card"
  aria-labelledby={headingId}
  data-testid="approval-card"
  data-approval-id={approval.id}
>
  <header class="card__header">
    <h2 id={headingId} class="card__title">
      Proposal <code>{proposalShort}</code>
    </h2>
    <div class="card__countdown" class:card__countdown--expired={expired}>
      <span class="card__countdown-label">Expires in</span>
      <time
        datetime={approval.expires_at}
        class="card__countdown-value"
        data-testid="countdown"
      >
        {countdown}
      </time>
    </div>
  </header>

  <dl class="card__meta">
    <div class="card__meta-row">
      <dt>Created</dt>
      <dd>
        <time datetime={approval.created_at}>{approval.created_at}</time>
      </dd>
    </div>
    <div class="card__meta-row">
      <dt>Timeout</dt>
      <dd>{approval.timeout_seconds}s</dd>
    </div>
  </dl>

  {#if approval.delivered_to_channels.length > 0}
    <div class="card__channels" data-testid="delivered-channels">
      <span class="card__channels-label">Delivered to</span>
      {#each approval.delivered_to_channels as channel (channel)}
        <Badge label={channel} variant="accent" />
      {/each}
    </div>
  {/if}

  {#if deliveryFailures.length > 0}
    <div class="card__channels" data-testid="delivery-failures">
      <span class="card__channels-label">Delivery failures</span>
      {#each deliveryFailures as failure, i (i)}
        <Badge label={failureChannel(failure)} variant="destructive" />
      {/each}
    </div>
  {/if}

  <div class="card__actions">
    <form method="POST" action="?/approve" use:enhance>
      <input type="hidden" name="request_id" value={approval.id} />
      <button
        type="submit"
        class="btn btn--primary"
        data-testid="approve-{approval.id}"
        disabled={expired}
      >
        Approve
      </button>
    </form>

    {#if !showRejectForm}
      <button
        type="button"
        class="btn btn--danger"
        data-testid="reject-toggle-{approval.id}"
        onclick={toggleReject}
        disabled={expired}
      >
        Reject
      </button>
    {:else}
      <form method="POST" action="?/reject" use:enhance class="card__reject-form">
        <input type="hidden" name="request_id" value={approval.id} />
        <Textarea
          name="reason"
          label="Rejection reason (optional)"
          bind:value={rejectReason}
          rows={3}
          monospace={false}
          placeholder="e.g. risk too high for the current session."
          helpText="Optional — the backend accepts a rejection with no reason."
        />
        <div class="card__reject-actions">
          <button
            type="submit"
            class="btn btn--danger"
            data-testid="reject-confirm-{approval.id}"
          >
            Confirm rejection
          </button>
          <button
            type="button"
            class="btn btn--ghost"
            data-testid="reject-cancel-{approval.id}"
            onclick={toggleReject}
          >
            Cancel
          </button>
        </div>
      </form>
    {/if}
  </div>
</article>

<style>
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    padding: 16px 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .card__header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 16px;
    flex-wrap: wrap;
  }
  .card__title {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--ink);
  }
  .card__title code {
    font-family: var(--font-mono);
    font-size: 13px;
    color: var(--accent);
  }
  .card__countdown {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    font-size: 13px;
    color: var(--mute);
  }
  .card__countdown-label {
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    font-size: 11px;
  }
  .card__countdown-value {
    font-family: var(--font-mono);
    font-size: 14px;
    color: var(--ink);
    font-weight: 600;
  }
  .card__countdown--expired .card__countdown-value {
    color: var(--destructive);
  }
  .card__meta {
    margin: 0;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 8px 16px;
  }
  .card__meta-row {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .card__meta-row dt {
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    font-size: 11px;
    color: var(--mute);
  }
  .card__meta-row dd {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 13px;
    color: var(--ink);
  }
  .card__channels {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
  }
  .card__channels-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    color: var(--mute);
    margin-right: 4px;
  }
  .card__actions {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 4px;
  }
  .card__reject-form {
    flex: 1 1 100%;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    padding: 12px 14px;
  }
  .card__reject-actions {
    display: flex;
    gap: 8px;
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
    line-height: 1.4;
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn--primary {
    background: var(--accent);
    color: var(--accent-fg);
  }
  .btn--primary:hover:not(:disabled) {
    background: var(--accent-hover);
  }
  .btn--ghost {
    background: transparent;
    color: var(--ink);
    border-color: var(--border);
  }
  .btn--ghost:hover:not(:disabled) {
    background: var(--surface-2);
  }
  .btn--danger {
    background: transparent;
    color: var(--destructive);
    border-color: oklch(64% 0.2 25 / 0.5);
  }
  .btn--danger:hover:not(:disabled) {
    background: oklch(64% 0.2 25 / 0.12);
  }
</style>
