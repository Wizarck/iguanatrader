<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * The nested `[symbol]` route inherits the section label from the
   * parent `/research/+page.svelte`; we still export `meta` so the
   * sidebar enumerator does not flag the route as "missing meta".
   */
  export const meta = {
    label: 'Research detail',
    icon: 'file-text',
    order: 41,
    hidden: true
  } as const;
</script>

<script lang="ts">
  import type { PageData } from './$types';
  import BriefHeader from '$lib/components/research/BriefHeader.svelte';
  import CitationLink from '$lib/components/research/CitationLink.svelte';
  import { parseCitations } from '$lib/research/parse-citations';

  type FactRow = {
    id: string;
    source_id: string;
    source_url?: string | null;
    retrieval_method?: 'api' | 'scrape' | 'manual' | 'llm' | null;
    retrieved_at?: string | null;
    fact_kind?: string;
    value_numeric?: number | string | null;
    value_text?: string | null;
    effective_from?: string;
  };

  let { data }: { data: PageData } = $props();

  let refreshing = $state(false);
  let refreshError = $state<string | null>(null);
  let currentBrief = $state(data.brief as Record<string, unknown> | null);

  let facts = $derived(data.facts as FactRow[]);

  // Build a fact-id → fact lookup for the citation tooltip data.
  let factById = $derived.by(() => {
    const map = new Map<string, FactRow>();
    for (const f of facts) {
      map.set(f.id, f);
    }
    return map;
  });

  let body = $derived(
    (currentBrief?.body_markdown as string | undefined) ??
      (currentBrief?.thesis_text as string | undefined) ??
      ''
  );
  let segments = $derived(parseCitations(body));

  async function refresh() {
    refreshing = true;
    refreshError = null;
    try {
      const res = await fetch(
        `/api/v1/research/briefs/${encodeURIComponent(data.symbol)}/refresh`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({})
        }
      );
      if (!res.ok) {
        const text = await res.text();
        refreshError = `Refresh failed (${res.status}): ${text.slice(0, 200)}`;
        return;
      }
      currentBrief = await res.json();
    } catch (err) {
      refreshError = err instanceof Error ? err.message : String(err);
    } finally {
      refreshing = false;
    }
  }
</script>

<svelte:head>
  <title>Research · {data.symbol} · iguanatrader</title>
</svelte:head>

<section>
  {#if currentBrief}
    <BriefHeader
      symbol={data.symbol}
      methodology={(currentBrief.methodology as string) ?? 'unknown'}
      version={(currentBrief.version as number) ?? 0}
      synthesizedAt={(currentBrief.created_at as string) ?? null}
      {refreshing}
      {refreshError}
      onRefresh={refresh}
    />

    {#if currentBrief.partial}
      <div role="status" class="warn">Partial brief — required tier-A features missing.</div>
    {/if}

    <article class="brief-body" aria-label="Brief summary">
      {#each segments as seg, i (i)}
        {#if seg.kind === 'text'}
          <span class="text-segment">{seg.value}</span>
        {:else}
          {@const fact = factById.get(seg.factId)}
          <CitationLink
            factId={seg.factId}
            sourceLabel={fact?.source_id ?? null}
            sourceUrl={fact?.source_url ?? null}
            retrievedAt={fact?.retrieved_at ?? null}
            method={fact?.retrieval_method ?? null}
          />
        {/if}
      {/each}
    </article>
  {:else}
    <article aria-label="No brief yet">
      <h1>Research — {data.symbol}</h1>
      <p>No brief synthesised yet for {data.symbol}.</p>
      <button type="button" onclick={refresh} disabled={refreshing}>
        {refreshing ? 'Synthesising…' : 'Refresh brief'}
      </button>
      {#if refreshError}
        <div role="alert" class="error">{refreshError}</div>
      {/if}
    </article>
  {/if}

  <section aria-label="Recent facts">
    <h2>Recent facts ({facts.length})</h2>
    {#if facts.length === 0}
      <p>No facts ingested yet for {data.symbol}.</p>
    {:else}
      <ul>
        {#each facts as fact, idx (fact.id ?? idx)}
          <li>
            <span class="fact-kind">{fact.fact_kind}</span>
            <span class="fact-source">{fact.source_id}</span>
            <span class="fact-value">{fact.value_numeric ?? fact.value_text ?? ''}</span>
            {#if fact.effective_from}
              <time datetime={fact.effective_from}>{fact.effective_from}</time>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</section>

<style>
  section {
    color: var(--ink);
    padding: 1rem;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
  }
  h2 {
    font-size: 18px;
    font-weight: 600;
    margin-top: 1.5rem;
  }
  button {
    padding: 0.5rem 1rem;
    background: var(--accent);
    color: var(--accent-fg);
    border: none;
    border-radius: 4px;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  .error {
    color: var(--err-fg, #c00);
    background: var(--err-bg, #fee);
    padding: 0.5rem;
    border-radius: 4px;
    margin: 1rem 0;
  }
  .warn {
    color: var(--warn-fg, #960);
    background: var(--warn-bg, #ffd);
    padding: 0.5rem;
    border-radius: 4px;
    margin: 0.5rem 0;
  }
  .brief-body {
    white-space: pre-wrap;
    word-wrap: break-word;
    font-family: var(--font-sans, sans-serif);
    background: var(--surface);
    padding: 1rem;
    border-radius: 4px;
    line-height: 1.55;
  }
  .text-segment {
    white-space: pre-wrap;
  }
  ul {
    list-style: none;
    padding: 0;
  }
  li {
    display: flex;
    gap: 1rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--mute);
  }
  .fact-kind {
    font-family: monospace;
    color: var(--accent);
  }
  .fact-source {
    color: var(--mute);
  }
  .fact-value {
    flex: 1;
  }
</style>
