<script lang="ts">
  import Badge from '$lib/components/Badge.svelte';
  import DataTable, { type DataTableColumn } from '$lib/components/DataTable.svelte';
  import type { FillOut, OrderOut } from '$lib/trades/types';
  import {
    orderRoleLabel,
    orderStateVariant,
    sideVariant,
    stateVariant
  } from '$lib/trades/variants';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  // Slice ``frontend-gaps-batch``: trade close form. Posts to
  // POST /api/v1/trades/{id}/close with a reason (one of stop /
  // target / manual / expiry). The endpoint emits CloseTradeRequested
  // → TradingService.close_trade_handler submits the exit order.
  let closeReason = $state<'manual' | 'stop' | 'target' | 'expiry'>('manual');
  let closeSubmitting = $state(false);
  let closeError = $state<string | null>(null);
  let closeSuccess = $state<string | null>(null);

  async function handleClose(event: Event) {
    event.preventDefault();
    if (!data.trade) return;
    closeSubmitting = true;
    closeError = null;
    closeSuccess = null;
    try {
      const res = await fetch(`/api/v1/trades/${data.trade.id}/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: closeReason })
      });
      if (!res.ok) {
        const detail = await res.text();
        closeError = `No se pudo cerrar (${res.status}): ${detail || res.statusText}`;
      } else {
        closeSuccess = 'Cierre enviado. El estado pasará a "closing" cuando el broker confirme.';
      }
    } catch (err) {
      closeError = err instanceof Error ? err.message : String(err);
    } finally {
      closeSubmitting = false;
    }
  }

  // Slice ``frontend-gaps-batch``: regenerate journal narrative. Posts
  // to /api/v1/trades/{id}/journal?regenerate=true. Only available
  // for closed trades.
  let journalSubmitting = $state(false);
  let journalError = $state<string | null>(null);
  let journalNarrative = $state<string | null>(null);
  $effect(() => {
    journalNarrative = data.trade?.journal_narrative ?? null;
  });

  async function handleJournalRegenerate() {
    if (!data.trade) return;
    journalSubmitting = true;
    journalError = null;
    try {
      const res = await fetch(`/api/v1/trades/${data.trade.id}/journal?regenerate=true`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      if (!res.ok) {
        journalError = `No se pudo regenerar (${res.status}): ${res.statusText}`;
      } else {
        const payload = (await res.json()) as { narrative: string };
        journalNarrative = payload.narrative;
      }
    } catch (err) {
      journalError = err instanceof Error ? err.message : String(err);
    } finally {
      journalSubmitting = false;
    }
  }

  const fillsColumns: DataTableColumn<FillOut>[] = [
    { key: 'filled_at', header: 'Filled at' },
    { key: 'quantity_filled', header: 'Qty' },
    { key: 'fill_price', header: 'Price' },
    { key: 'commission', header: 'Commission' },
    { key: 'broker_fill_id', header: 'Broker fill ID' }
  ];
</script>

<svelte:head>
  <title>Trade · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <p class="back">
    <a href="/trades" data-testid="trades-back-link">← Volver a trades</a>
  </p>

  <h1>Detalle del trade</h1>

  {#if data.loadError}
    <div class="error" role="alert" data-testid="trade-load-error">
      {data.loadError}
    </div>
  {:else if data.trade}
    <article class="summary" data-testid="trade-summary">
      <header class="summary-header">
        <h2 class="symbol">{data.trade.symbol}</h2>
        <Badge label={data.trade.side} variant={sideVariant(data.trade.side)} />
        <Badge label={data.trade.state} variant={stateVariant(data.trade.state)} />
      </header>
      <dl class="summary-grid">
        <dt>Quantity</dt>
        <dd>{data.trade.quantity}</dd>
        <dt>Mode</dt>
        <dd>{data.trade.mode}</dd>
        <dt>Opened</dt>
        <dd>{data.trade.opened_at}</dd>
        <dt>Closed</dt>
        <dd>{data.trade.closed_at ?? '—'}</dd>
        <dt>Trade ID</dt>
        <dd><code>{data.trade.id}</code></dd>
      </dl>
    </article>

    {#if data.trade.state === 'open'}
      <section class="close-form" data-testid="close-trade-form">
        <h2>Cerrar trade</h2>
        <p class="hint">
          Envía una <code>CloseTradeRequested</code> al daemon. El estado pasa a
          <code>closing</code> al confirmar el broker, y a <code>closed</code> cuando
          el fill terminal aterriza. La razón se persiste en
          <code>trades.exit_reason</code> y la usa el K1 stoploss_guard.
        </p>
        <form onsubmit={handleClose}>
          <label>
            <span>Razón</span>
            <select bind:value={closeReason} disabled={closeSubmitting}>
              <option value="manual">manual — cierre operador</option>
              <option value="stop">stop — disparado por stop-loss</option>
              <option value="target">target — take-profit alcanzado</option>
              <option value="expiry">expiry — vencimiento (opciones / futuros)</option>
            </select>
          </label>
          <button type="submit" class="primary" disabled={closeSubmitting}>
            {closeSubmitting ? 'Enviando...' : 'Cerrar trade'}
          </button>
        </form>
        {#if closeError}
          <div class="error" role="alert">{closeError}</div>
        {/if}
        {#if closeSuccess}
          <div class="success" role="status">{closeSuccess}</div>
        {/if}
      </section>
    {/if}

    {#if data.trade.state === 'closed'}
      <section class="journal" data-testid="journal-section">
        <h2>Journal post-mortem (LLM)</h2>
        {#if journalNarrative}
          <article class="narrative">{journalNarrative}</article>
          <button type="button" onclick={handleJournalRegenerate} disabled={journalSubmitting}>
            {journalSubmitting ? 'Regenerando...' : 'Regenerar narrativa'}
          </button>
        {:else}
          <p class="hint">Aún no hay narrativa generada para este trade.</p>
          <button type="button" onclick={handleJournalRegenerate} disabled={journalSubmitting}>
            {journalSubmitting ? 'Generando...' : 'Generar narrativa'}
          </button>
        {/if}
        {#if journalError}
          <div class="error" role="alert">{journalError}</div>
        {/if}
      </section>
    {/if}

    <section class="orders" data-testid="orders-timeline">
      <h2>Order timeline</h2>
      {#if data.orders.length === 0}
        <p class="orders-empty" data-testid="orders-empty">Sin orders aún.</p>
      {:else}
        <ol class="timeline">
          {#each data.orders as order (order.id)}
            <li class="timeline-row" data-testid="order-row" data-order-state={order.state}>
              <div class="timeline-head">
                <span class="role">
                  {orderRoleLabel(order.side, order.order_type, data.trade.side)}
                </span>
                <Badge label={order.state} variant={orderStateVariant(order.state)} />
              </div>
              <dl class="timeline-grid">
                <dt>Type</dt>
                <dd>{order.order_type}</dd>
                <dt>Side</dt>
                <dd>{order.side}</dd>
                <dt>Qty</dt>
                <dd>{order.quantity}</dd>
                {#if order.limit_price}
                  <dt>Limit</dt>
                  <dd>{order.limit_price}</dd>
                {/if}
                {#if order.stop_price}
                  <dt>Stop</dt>
                  <dd>{order.stop_price}</dd>
                {/if}
                {#if order.broker_order_id}
                  <dt>Broker ID</dt>
                  <dd><code>{order.broker_order_id}</code></dd>
                {/if}
                <dt>Submitted</dt>
                <dd>{order.submitted_at ?? '—'}</dd>
                <dt>Acknowledged</dt>
                <dd>{order.acknowledged_at ?? '—'}</dd>
                <dt>Closed</dt>
                <dd>{order.closed_at ?? '—'}</dd>
              </dl>
            </li>
          {/each}
        </ol>
      {/if}
    </section>

    <h2 class="fills-heading">Fills</h2>
    {#if data.fills.length === 0}
      <p class="fills-empty" data-testid="fills-empty">Sin fills aún.</p>
    {:else}
      <DataTable
        rows={data.fills}
        columns={fillsColumns}
        rowKey={(f) => f.id}
      />
    {/if}
  {/if}
</section>

<style>
  section {
    color: var(--ink);
  }
  .back {
    margin: 0 0 12px;
  }
  .back a {
    color: var(--accent);
    font-size: 14px;
    text-decoration: none;
  }
  .back a:hover {
    text-decoration: underline;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 16px;
  }
  .summary {
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
    padding: 20px 24px;
    max-width: 720px;
  }
  .summary-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }
  .summary-header .symbol {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    color: var(--ink);
  }
  .summary-grid {
    display: grid;
    grid-template-columns: 140px 1fr;
    gap: 8px 16px;
    margin: 0;
    font-size: 14px;
  }
  .summary-grid dt {
    color: var(--mute);
    font-weight: 500;
  }
  .summary-grid dd {
    margin: 0;
    color: var(--ink);
  }
  .summary-grid code {
    color: var(--accent);
    font-family: var(--font-mono);
    font-size: 12px;
  }
  .fills-heading {
    font-size: 16px;
    font-weight: 600;
    margin: 24px 0 12px;
    color: var(--ink);
  }
  .fills-empty {
    margin: 0;
    color: var(--mute);
    font-size: 14px;
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
  .success {
    margin-top: 16px;
    padding: 12px 16px;
    background: oklch(70% 0.18 145 / 0.12);
    border: 1px solid oklch(70% 0.18 145 / 0.35);
    border-radius: var(--r-2);
    color: oklch(70% 0.18 145);
    font-size: 14px;
  }
  .close-form,
  .journal {
    margin: 24px 0;
    padding: 20px 24px;
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
    max-width: 720px;
  }
  .close-form h2,
  .journal h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 0 0 12px;
  }
  .close-form .hint,
  .journal .hint {
    margin: 0 0 16px;
    color: var(--mute);
    font-size: 13px;
    line-height: 1.5;
  }
  .close-form .hint code,
  .journal .hint code {
    background: oklch(98% 0.01 240 / 0.04);
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 12px;
    color: var(--accent);
  }
  .close-form form {
    display: flex;
    gap: 12px;
    align-items: flex-end;
  }
  .close-form label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 13px;
    color: var(--mute);
    flex: 1;
  }
  .close-form select {
    padding: 8px 10px;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--ink);
    border-radius: var(--r-1);
    font-size: 14px;
  }
  .close-form button.primary,
  .journal button {
    padding: 9px 18px;
    border: 1px solid var(--accent);
    background: var(--accent);
    color: var(--bg);
    border-radius: var(--r-1);
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
  }
  .close-form button.primary:disabled,
  .journal button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  .journal .narrative {
    white-space: pre-wrap;
    background: oklch(98% 0.01 240 / 0.03);
    border: 1px solid var(--border);
    border-radius: var(--r-1);
    padding: 12px 14px;
    font-size: 13px;
    line-height: 1.55;
    margin: 0 0 12px;
    color: var(--ink);
  }
  .orders {
    margin: 24px 0;
    max-width: 720px;
  }
  .orders h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 0 0 12px;
    color: var(--ink);
  }
  .orders-empty {
    margin: 0;
    color: var(--mute);
    font-size: 14px;
    font-style: italic;
  }
  .timeline {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 12px;
  }
  .timeline-row {
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
    padding: 14px 18px;
  }
  .timeline-head {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 10px;
  }
  .timeline-head .role {
    font-weight: 600;
    font-size: 14px;
    color: var(--ink);
  }
  .timeline-grid {
    display: grid;
    grid-template-columns: 110px 1fr;
    gap: 4px 14px;
    margin: 0;
    font-size: 13px;
  }
  .timeline-grid dt {
    color: var(--mute);
    font-weight: 500;
  }
  .timeline-grid dd {
    margin: 0;
    color: var(--ink);
  }
  .timeline-grid code {
    color: var(--accent);
    font-family: var(--font-mono);
    font-size: 12px;
  }
</style>
