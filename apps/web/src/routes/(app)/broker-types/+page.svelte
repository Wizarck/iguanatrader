<script module lang="ts">
  export const meta = {
    label: 'Broker types',
    icon: 'cpu',
    order: 80
  } as const;
</script>

<script lang="ts">
  import type { BrokerTypeOption } from '$lib/broker/types';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  // Each entry collapses by default; clicking the row toggles. State
  // is per-section/per-code so a long scroll doesn't lose context.
  let openCodes = $state<Set<string>>(new Set());

  function toggle(section: string, code: string): void {
    const key = `${section}::${code}`;
    const next = new Set(openCodes);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    openCodes = next;
  }

  function isOpen(section: string, code: string): boolean {
    return openCodes.has(`${section}::${code}`);
  }
</script>

<svelte:head>
  <title>Broker types · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <header class="page-header">
    <h1>IBKR catalogue — sec_type / order_type / algo_kind</h1>
    <p class="hint">
      Vocabulary the daemon accepts when building contracts + orders via
      <code>ib_async</code>. Source-of-truth in
      <code>contexts/trading/brokers/translator_docs.py</code> and served by
      <code>GET /api/v1/broker/types</code> so this page and future
      order-builder forms share the copy without duplication.
    </p>
  </header>

  {#if data.loadError}
    <div class="error" role="alert">{data.loadError}</div>
  {:else if data.catalogue}
    {#snippet catalogueGroup(title: string, items: BrokerTypeOption[], section: string)}
      <h2>{title}</h2>
      <ul class="entries">
        {#each items as opt (opt.code)}
          {@const open = isOpen(section, opt.code)}
          <li class="entry" class:open>
            <button
              type="button"
              class="entry-head"
              onclick={() => toggle(section, opt.code)}
              aria-expanded={open}
            >
              <span class="code">{opt.code}</span>
              <span class="label">{opt.label}</span>
              {#if opt.required_fields.length > 0}
                <span class="required">requires: {opt.required_fields.join(', ')}</span>
              {/if}
              <span class="chevron" aria-hidden="true">{open ? '▾' : '▸'}</span>
            </button>
            {#if open}
              <div class="entry-body">
                {#each opt.description.split('\n\n') as paragraph}
                  <p>{paragraph}</p>
                {/each}
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/snippet}

    {@render catalogueGroup('Contract sec_type', data.catalogue.sec_types, 'sec')}
    {@render catalogueGroup('Order type', data.catalogue.order_types, 'ord')}
    {@render catalogueGroup('Execution algo (algo_kind)', data.catalogue.algo_kinds, 'algo')}
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
  .page-header code,
  .entry code,
  .entry-body code {
    background: oklch(98% 0.01 240 / 0.05);
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 12px;
    color: var(--accent);
    font-family: var(--font-mono);
  }
  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 24px 0 8px;
    color: var(--ink);
  }
  .entries {
    list-style: none;
    padding: 0;
    margin: 0;
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
    overflow: hidden;
  }
  .entry {
    border-bottom: 1px solid var(--border);
  }
  .entry:last-child {
    border-bottom: none;
  }
  .entry-head {
    width: 100%;
    background: transparent;
    border: none;
    text-align: left;
    cursor: pointer;
    padding: 12px 16px;
    display: grid;
    grid-template-columns: 96px 1fr auto 16px;
    align-items: center;
    gap: 12px;
    color: var(--ink);
    font-size: 14px;
  }
  .entry-head:hover {
    background: var(--surface-2);
  }
  .entry.open .entry-head {
    background: var(--surface-2);
  }
  .entry .code {
    font-family: var(--font-mono);
    color: var(--accent);
    font-size: 12px;
    font-weight: 600;
  }
  .entry .label {
    color: var(--ink);
    font-weight: 500;
  }
  .entry .required {
    color: var(--mute);
    font-size: 12px;
    font-style: italic;
  }
  .entry .chevron {
    color: var(--mute);
    font-size: 12px;
  }
  .entry-body {
    padding: 4px 16px 16px;
    border-top: 1px solid var(--border);
    background: var(--surface);
  }
  .entry-body p {
    margin: 8px 0;
    color: var(--ink);
    font-size: 13px;
    line-height: 1.55;
    white-space: pre-wrap;
  }
  .entry-body p:first-child {
    margin-top: 12px;
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
