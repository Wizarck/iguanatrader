<script lang="ts">
  import { SvelteSet } from 'svelte/reactivity';

  import Badge, { type BadgeVariant } from '$lib/components/Badge.svelte';
  import { formatMoney, formatPercent } from '$lib/portfolio/format';
  import type { PositionOut } from '$lib/portfolio/types';

  type Props = {
    positions: PositionOut[];
    currency: string;
  };

  let { positions, currency }: Props = $props();

  // Expanded trade_ids — default empty (all rows collapsed).
  const expanded = new SvelteSet<string>();

  function toggle(tradeId: string): void {
    if (expanded.has(tradeId)) {
      expanded.delete(tradeId);
    } else {
      expanded.add(tradeId);
    }
  }

  // Summary row has 8 columns → the detail row's single cell spans all of them.
  const COLSPAN = 8;

  const qtyFormatter = new Intl.NumberFormat('en-US', { maximumFractionDigits: 8 });
  const dateFormatter = new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  });

  function formatQty(quantity: string): string {
    return qtyFormatter.format(Number(quantity));
  }

  function formatOpened(openedAt: string): string {
    const d = new Date(openedAt);
    return Number.isNaN(d.getTime()) ? openedAt : dateFormatter.format(d);
  }

  type VerdictInfo = { label: string; variant: BadgeVariant };

  function verdictInfo(verdict: string | null): VerdictInfo {
    switch (verdict) {
      case 'on_track':
        return { label: 'On track', variant: 'success' };
      case 'off_track':
        return { label: 'Off track', variant: 'destructive' };
      case 'too_early':
        return { label: 'Too early', variant: 'neutral' };
      default:
        // 'no_data' or null
        return { label: 'No data', variant: 'mute' };
    }
  }

  // Colour the P&L green/red ONLY for actionable verdicts — a small early move
  // shouldn't scream when it's "too_early" or "no_data".
  function pnlColored(verdict: string | null): boolean {
    return verdict === 'on_track' || verdict === 'off_track';
  }

  // Client-side P&L %: unrealized_pnl / (avg_entry_price * quantity). All inputs
  // are Decimal-as-string; guard nulls/non-finite → "—".
  function pnlPercent(position: PositionOut): string {
    const { unrealized_pnl, avg_entry_price, quantity } = position;
    if (unrealized_pnl === null || avg_entry_price === null) return '—';
    const pnl = Number(unrealized_pnl);
    const entry = Number(avg_entry_price);
    const qty = Number(quantity);
    const cost = entry * qty;
    if (!Number.isFinite(pnl) || !Number.isFinite(cost) || cost === 0) return '—';
    return formatPercent(String(pnl / cost));
  }

  // Bar width for rail progress, clamped to [0, 1]; null/non-finite → 0.
  function railFraction(railProgress: string | null): number {
    if (railProgress === null) return 0;
    const v = Number(railProgress);
    if (!Number.isFinite(v)) return 0;
    return Math.min(1, Math.max(0, v));
  }

  // Render the "why it fired" reasoning object as readable `key: value` lines.
  // Nested values are JSON-stringified compactly.
  function reasoningEntries(
    reasoning: Record<string, unknown> | null
  ): Array<{ key: string; value: string }> {
    if (reasoning === null || typeof reasoning !== 'object') return [];
    return Object.entries(reasoning).map(([key, value]) => ({
      key,
      value:
        value === null || typeof value !== 'object'
          ? String(value)
          : JSON.stringify(value)
    }));
  }
</script>

<div class="positions-wrap">
  <table class="positions" data-testid="positions-table">
    <thead>
      <tr>
        <th scope="col" class="col-expand"><span class="sr-only">Expand</span></th>
        <th scope="col">Symbol</th>
        <th scope="col">Side</th>
        <th scope="col">Strategy</th>
        <th scope="col" class="num">Qty</th>
        <th scope="col">Verdict</th>
        <th scope="col" class="num">Unrealized P&amp;L</th>
        <th scope="col">Opened</th>
      </tr>
    </thead>
    <tbody>
      {#each positions as position (position.trade_id)}
        {@const isOpen = expanded.has(position.trade_id)}
        {@const panelId = `position-detail-${position.trade_id}`}
        {@const verdict = verdictInfo(position.verdict)}
        <tr class="summary-row" data-testid="position-row">
          <td class="col-expand">
            <button
              type="button"
              class="expand-btn"
              aria-expanded={isOpen}
              aria-controls={panelId}
              onclick={() => toggle(position.trade_id)}
            >
              <span class="chevron" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
              <span class="sr-only">
                {isOpen ? 'Collapse' : 'Expand'}
                {position.symbol} details
              </span>
            </button>
          </td>
          <td class="symbol">{position.symbol}</td>
          <td>
            <Badge
              label={position.side === 'buy' ? 'LONG' : 'SHORT'}
              variant="accent"
            />
          </td>
          <td>{position.strategy_kind ?? '—'}</td>
          <td class="num">{formatQty(position.quantity)}</td>
          <td>
            <Badge label={verdict.label} variant={verdict.variant} />
          </td>
          <td class="num">
            <span
              class="pnl"
              class:pnl--colored={pnlColored(position.verdict)}
              class:pnl--up={pnlColored(position.verdict) &&
                Number(position.unrealized_pnl) > 0}
              class:pnl--down={pnlColored(position.verdict) &&
                Number(position.unrealized_pnl) < 0}
            >
              {formatMoney(position.unrealized_pnl, currency)}
              <span class="pnl-pct">({pnlPercent(position)})</span>
            </span>
          </td>
          <td class="opened">
            <time datetime={position.opened_at} title={position.opened_at}>
              {formatOpened(position.opened_at)}
            </time>
            <span class="held">· {position.held_market_days ?? '—'} market days</span>
          </td>
        </tr>
        {#if isOpen}
          <tr class="detail-row" data-testid="position-detail-row">
            <td colspan={COLSPAN}>
              <div class="panel" id={panelId}>
                <p class="verdict-reason">{position.verdict_reason ?? '—'}</p>

                <div class="rails">
                  <div class="rail">
                    <span class="rail-label">Planned entry</span>
                    <span class="rail-value"
                      >{formatMoney(position.entry_price_indicative, currency)}</span
                    >
                  </div>
                  <div class="rail">
                    <span class="rail-label">Avg fill</span>
                    <span class="rail-value"
                      >{formatMoney(position.avg_entry_price, currency)}</span
                    >
                  </div>
                  <div class="rail">
                    <span class="rail-label">Last</span>
                    <span class="rail-value"
                      >{formatMoney(position.last_price, currency)}</span
                    >
                  </div>
                  <div class="rail">
                    <span class="rail-label">Stop</span>
                    <span class="rail-value"
                      >{formatMoney(position.stop_price, currency)}</span
                    >
                  </div>
                  <div class="rail">
                    <span class="rail-label">Target</span>
                    <span class="rail-value"
                      >{formatMoney(position.target_price, currency)}</span
                    >
                  </div>
                </div>

                <div class="scorecard">
                  <div class="metric">
                    <span class="metric-label">R-multiple</span>
                    <span class="metric-value"
                      >{position.r_multiple ?? '—'} R</span
                    >
                  </div>
                  <div class="metric">
                    <span class="metric-label">Reward:risk</span>
                    <span class="metric-value">{position.reward_risk ?? '—'}</span>
                  </div>
                  <div class="metric metric--rail">
                    <span class="metric-label">Rail progress</span>
                    <span class="rail-progress">
                      <span class="rail-progress-track">
                        <span
                          class="rail-progress-fill"
                          style="width: {railFraction(position.rail_progress) * 100}%"
                        ></span>
                      </span>
                      <span class="metric-value"
                        >{position.rail_progress ?? '—'}</span
                      >
                    </span>
                  </div>
                </div>

                <div class="meta">
                  <p class="meta-line">
                    <span class="meta-label">Horizon:</span>
                    {position.horizon_label ?? 'unknown'} · ~{position.horizon_days ??
                      '—'} market days
                  </p>
                  <p class="meta-line">
                    <span class="meta-label">Held:</span>
                    {position.held_market_days ?? '—'} market days
                  </p>
                  <p class="meta-line">
                    {#if position.confidence_score != null}
                      Model conviction: {Math.round(
                        Number(position.confidence_score) * 100
                      )}% · not a win-probability
                    {:else}
                      Model conviction: not recorded
                    {/if}
                  </p>
                </div>

                <div class="reasoning">
                  <span class="meta-label">Why it fired</span>
                  {#if position.reasoning === null}
                    <p class="reasoning-empty">—</p>
                  {:else}
                    {@const entries = reasoningEntries(position.reasoning)}
                    {#if entries.length === 0}
                      <p class="reasoning-empty">—</p>
                    {:else}
                      <ul class="reasoning-list">
                        {#each entries as entry (entry.key)}
                          <li>
                            <span class="reasoning-key">{entry.key}:</span>
                            <span class="reasoning-val">{entry.value}</span>
                          </li>
                        {/each}
                      </ul>
                    {/if}
                  {/if}
                </div>
              </div>
            </td>
          </tr>
        {/if}
      {/each}
    </tbody>
  </table>
</div>

<style>
  .positions-wrap {
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
  }
  table.positions {
    width: 100%;
    border-collapse: collapse;
    color: var(--ink);
    font-size: 14px;
  }
  thead th {
    text-align: left;
    padding: 10px 12px;
    background: var(--surface-2);
    border-bottom: 1px solid var(--border);
    color: var(--mute);
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  th.num,
  td.num {
    text-align: right;
  }
  td.col-expand,
  th.col-expand {
    width: 1%;
    padding-right: 0;
  }
  .summary-row td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
  }
  .summary-row .symbol {
    font-weight: 700;
  }
  .expand-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--r-2);
    color: var(--mute);
    cursor: pointer;
    line-height: 1;
  }
  .expand-btn:hover {
    background: var(--surface-2);
    color: var(--ink);
  }
  .expand-btn:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  .chevron {
    font-size: 12px;
  }
  .pnl {
    color: var(--mute);
    white-space: nowrap;
  }
  .pnl--colored {
    color: var(--ink);
  }
  .pnl--up {
    color: var(--success);
  }
  .pnl--down {
    color: var(--destructive);
  }
  .pnl-pct {
    color: var(--mute);
    font-size: 12px;
  }
  .pnl--up .pnl-pct,
  .pnl--down .pnl-pct {
    color: inherit;
    opacity: 0.85;
  }
  .opened {
    white-space: nowrap;
  }
  .held {
    color: var(--mute);
    font-size: 12px;
  }

  /* Detail panel */
  .detail-row td {
    padding: 0;
    border-bottom: 1px solid var(--border);
    background: var(--surface-2);
  }
  .panel {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 16px 16px 18px 44px;
  }
  .verdict-reason {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--ink);
  }
  .rails {
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
  }
  .rail {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 88px;
  }
  .rail-label {
    color: var(--mute);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .rail-value {
    color: var(--ink);
    font-size: 14px;
    font-variant-numeric: tabular-nums;
  }
  .scorecard {
    display: flex;
    flex-wrap: wrap;
    gap: 24px;
    align-items: flex-start;
  }
  .metric {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .metric--rail {
    flex: 1 1 200px;
    min-width: 180px;
  }
  .metric-label {
    color: var(--mute);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .metric-value {
    color: var(--ink);
    font-size: 14px;
    font-variant-numeric: tabular-nums;
  }
  .rail-progress {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .rail-progress-track {
    position: relative;
    flex: 1 1 auto;
    height: 6px;
    min-width: 80px;
    background: var(--border);
    border-radius: var(--r-pill, 9999px);
    overflow: hidden;
  }
  .rail-progress-fill {
    position: absolute;
    inset: 0 auto 0 0;
    height: 100%;
    background: var(--accent);
    border-radius: var(--r-pill, 9999px);
  }
  .meta {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .meta-line {
    margin: 0;
    font-size: 13px;
    color: var(--ink);
  }
  .meta-label {
    color: var(--mute);
    font-weight: 600;
  }
  .reasoning {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .reasoning-empty {
    margin: 0;
    color: var(--mute);
  }
  .reasoning-list {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .reasoning-list li {
    font-size: 13px;
    color: var(--ink);
  }
  .reasoning-key {
    color: var(--mute);
    font-weight: 600;
  }
  .reasoning-val {
    font-variant-numeric: tabular-nums;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
</style>
