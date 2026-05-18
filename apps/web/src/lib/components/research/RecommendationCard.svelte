<script lang="ts" module>
  /**
   * Recommendation card (slice U3).
   *
   * Surfaces the structured ``## Recommendation`` section the brief
   * synthesizer emits — Action / Target / Horizon / Key risks — as a
   * distinct card above the pillar prose. Replaces the previous
   * inline-markdown rendering so the operator sees the call AND the
   * rationale at a glance instead of having to read the first
   * paragraph of body text.
   *
   * Visual treatment:
   *   - BUY  → success-green chip
   *   - HOLD → warn-amber chip
   *   - AVOID → error-red chip
   *   - Unknown / low-confidence → mute neutral chip with subtitle.
   */
  import type { ParsedRecommendation } from '$lib/research/parse-recommendation';
  export type { ParsedRecommendation };
</script>

<script lang="ts">
  type Props = {
    recommendation: ParsedRecommendation;
  };

  let { recommendation }: Props = $props();

  function _classFor(action: ParsedRecommendation['action']): string {
    if (action === 'BUY') return 'chip-buy';
    if (action === 'HOLD') return 'chip-hold';
    if (action === 'AVOID') return 'chip-avoid';
    return 'chip-unknown';
  }

  function _formatTarget(reco: ParsedRecommendation): string {
    if (reco.targetPrice !== null) {
      return `Target $${reco.targetPrice.toFixed(2)}`;
    }
    if (reco.targetPriceLabel) {
      return `Target ${reco.targetPriceLabel}`;
    }
    return 'Target —';
  }

  let actionClass = $derived(_classFor(recommendation.action));
  let targetLabel = $derived(_formatTarget(recommendation));
</script>

<section
  class="reco-card"
  data-action={recommendation.action ?? 'unknown'}
  aria-label="Brief recommendation"
>
  <header>
    <span class="action-chip {actionClass}">
      {recommendation.action ?? 'PENDING'}
    </span>
    <div class="meta">
      <span class="target">{targetLabel}</span>
      {#if recommendation.horizon}
        <span class="horizon">· {recommendation.horizon}</span>
      {/if}
    </div>
  </header>

  {#if recommendation.lowConfidence}
    <p class="confidence">
      Low-confidence rating — required tier-A inputs missing.
    </p>
  {/if}

  {#if recommendation.risks.length > 0}
    <div class="risks">
      <h3>Key risks</h3>
      <ul>
        {#each recommendation.risks as risk, i (i)}
          <li>{risk}</li>
        {/each}
      </ul>
    </div>
  {/if}
</section>

<style>
  .reco-card {
    background: var(--surface);
    border: 1px solid var(--mute);
    border-radius: 6px;
    padding: 16px 20px;
    margin-bottom: 16px;
  }
  header {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }
  .action-chip {
    display: inline-flex;
    align-items: center;
    padding: 6px 14px;
    border-radius: 999px;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.04em;
    background: var(--mute, #888);
    color: var(--accent-fg, #fff);
  }
  .action-chip.chip-buy {
    background: var(--success, #2da44e);
    color: #fff;
  }
  .action-chip.chip-hold {
    background: var(--warn-fg, #b48a00);
    color: #fff;
  }
  .action-chip.chip-avoid {
    background: var(--destructive, #cf222e);
    color: #fff;
  }
  .action-chip.chip-unknown {
    background: var(--surface-hover, rgba(255, 255, 255, 0.12));
    color: var(--ink);
    border: 1px dashed var(--mute);
  }
  .meta {
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-variant-numeric: tabular-nums;
  }
  .meta .target {
    font-size: 18px;
    font-weight: 600;
    color: var(--ink);
  }
  .meta .horizon {
    font-size: 13px;
    color: var(--mute);
  }
  .confidence {
    margin: 12px 0 0;
    padding: 8px 12px;
    background: var(--warn-bg, rgba(180, 138, 0, 0.12));
    color: var(--warn-fg, #b48a00);
    border-radius: 4px;
    font-size: 13px;
  }
  .risks {
    margin-top: 14px;
  }
  .risks h3 {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--mute);
    margin: 0 0 6px;
  }
  .risks ul {
    margin: 0;
    padding-left: 1.25rem;
  }
  .risks li {
    color: var(--ink);
    line-height: 1.5;
    font-size: 14px;
    margin: 2px 0;
  }
</style>
