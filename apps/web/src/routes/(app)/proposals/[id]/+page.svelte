<script lang="ts">
  import Badge from '$lib/components/Badge.svelte';
  import { sideVariant } from '$lib/trades/variants';
  import type { ExplainResponse, RiskReviewResponse } from '$lib/proposals/types';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  // Slice ``frontend-gaps-batch``: explain action — calls
  // POST /api/v1/proposals/{id}/explain (or via MCP tools). We use
  // the direct route here since the user is authenticated.
  let explainLoading = $state(false);
  let explainError = $state<string | null>(null);
  let explainNarrative = $state<string | null>(null);

  async function runExplain() {
    if (!data.proposal) return;
    explainLoading = true;
    explainError = null;
    try {
      const res = await fetch(`/api/v1/proposals/${data.proposal.id}/explain`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      if (!res.ok) {
        explainError = `Explain failed (${res.status}): ${res.statusText}`;
      } else {
        const payload = (await res.json()) as ExplainResponse;
        explainNarrative = payload.narrative;
      }
    } catch (err) {
      explainError = err instanceof Error ? err.message : String(err);
    } finally {
      explainLoading = false;
    }
  }

  let riskLoading = $state(false);
  let riskError = $state<string | null>(null);
  let riskResult = $state<RiskReviewResponse['risk_assessment'] | null>(null);

  async function runRiskReview() {
    if (!data.proposal) return;
    riskLoading = true;
    riskError = null;
    try {
      const res = await fetch(`/api/v1/proposals/${data.proposal.id}/risk-review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      if (!res.ok) {
        riskError = `Risk-review failed (${res.status}): ${res.statusText}`;
      } else {
        const payload = (await res.json()) as RiskReviewResponse;
        riskResult = payload.risk_assessment;
      }
    } catch (err) {
      riskError = err instanceof Error ? err.message : String(err);
    } finally {
      riskLoading = false;
    }
  }
</script>

<svelte:head>
  <title>Proposal · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <p class="back"><a href="/proposals">← Back to proposals</a></p>
  <h1>Proposal detail</h1>

  {#if data.loadError}
    <div class="error" role="alert">{data.loadError}</div>
  {:else if data.proposal}
    <article class="summary">
      <header class="summary-header">
        <h2>{data.proposal.symbol}</h2>
        <Badge label={data.proposal.side} variant={sideVariant(data.proposal.side)} />
        <Badge label={data.proposal.mode} variant="muted" />
      </header>
      <dl class="summary-grid">
        <dt>Quantity</dt><dd>{data.proposal.quantity}</dd>
        <dt>Entry (ind.)</dt><dd>{data.proposal.entry_price_indicative}</dd>
        <dt>Stop</dt><dd>{data.proposal.stop_price}</dd>
        <dt>Target</dt><dd>{data.proposal.target_price ?? '—'}</dd>
        <dt>Confidence</dt><dd>{data.proposal.confidence_score ?? '—'}</dd>
        <dt>Brief</dt>
        <dd>
          {#if data.proposal.research_brief_id}
            <code>{data.proposal.research_brief_id}</code>
          {:else}
            —
          {/if}
        </dd>
        <dt>Created</dt><dd>{data.proposal.created_at}</dd>
        <dt>Proposal ID</dt><dd><code>{data.proposal.id}</code></dd>
      </dl>
    </article>

    <section class="actions">
      <h2>LLM actions</h2>
      <p class="hint">
        Both actions consume LLM budget (A0 cap) and trigger calls
        to Anthropic. Results for each render below.
      </p>
      <div class="action-row">
        <button type="button" onclick={runExplain} disabled={explainLoading}>
          {explainLoading ? 'Generating…' : 'Explain proposal (A1)'}
        </button>
        <button type="button" onclick={runRiskReview} disabled={riskLoading}>
          {riskLoading ? 'Analyzing…' : 'Risk review (A2)'}
        </button>
      </div>
    </section>

    {#if explainNarrative}
      <section class="result" data-testid="explain-result">
        <h3>Narrative (explain)</h3>
        <article class="narrative">{explainNarrative}</article>
      </section>
    {/if}
    {#if explainError}
      <div class="error" role="alert">{explainError}</div>
    {/if}

    {#if riskResult}
      <section class="result" data-testid="risk-result">
        <h3>Risk review</h3>
        <dl class="summary-grid">
          <dt>Risk score</dt><dd>{riskResult.risk_score} / 100</dd>
          <dt>Flags</dt>
          <dd>
            {#if riskResult.flags.length === 0}
              —
            {:else}
              <ul class="flags">
                {#each riskResult.flags as flag}
                  <li>{flag}</li>
                {/each}
              </ul>
            {/if}
          </dd>
        </dl>
        <h4>Rationale</h4>
        <article class="narrative">{riskResult.rationale}</article>
      </section>
    {/if}
    {#if riskError}
      <div class="error" role="alert">{riskError}</div>
    {/if}
  {/if}
</section>

<style>
  section {
    color: var(--ink);
  }
  .back { margin: 0 0 12px; }
  .back a { color: var(--accent); font-size: 14px; text-decoration: none; }
  .back a:hover { text-decoration: underline; }
  h1 { font-size: 22px; font-weight: 600; margin: 0 0 16px; }
  .summary, .actions, .result {
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
    padding: 20px 24px;
    max-width: 720px;
    margin: 16px 0;
  }
  .summary-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
  .summary-header h2 { margin: 0; font-size: 18px; }
  .summary-grid { display: grid; grid-template-columns: 140px 1fr; gap: 8px 16px; margin: 0; font-size: 14px; }
  .summary-grid dt { color: var(--mute); font-weight: 500; }
  .summary-grid dd { margin: 0; color: var(--ink); }
  .summary-grid code { color: var(--accent); font-family: var(--font-mono); font-size: 12px; }
  .actions h2, .result h3 { margin: 0 0 12px; font-size: 16px; font-weight: 600; }
  .actions .hint { margin: 0 0 16px; color: var(--mute); font-size: 13px; line-height: 1.5; }
  .action-row { display: flex; gap: 12px; }
  button {
    padding: 9px 18px;
    border: 1px solid var(--accent);
    background: var(--accent);
    color: var(--bg);
    border-radius: var(--r-1);
    font-size: 14px;
    cursor: pointer;
  }
  button:disabled { opacity: 0.6; cursor: not-allowed; }
  .narrative {
    white-space: pre-wrap;
    background: oklch(98% 0.01 240 / 0.03);
    border: 1px solid var(--border);
    border-radius: var(--r-1);
    padding: 12px 14px;
    font-size: 13px;
    line-height: 1.55;
    margin: 0;
  }
  .result h4 { margin: 16px 0 8px; font-size: 14px; }
  .flags { margin: 0; padding-left: 20px; }
  .flags li { font-size: 13px; }
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
