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
  import BriefHeader from '$lib/components/research/BriefHeader.svelte';
  import FactTimeline, {
    type FactTimelineRow
  } from '$lib/components/research/FactTimeline.svelte';
  import StatBlock, { type BriefStats } from '$lib/components/research/StatBlock.svelte';
  import { readRecent, recordRecent, writeRecent } from '$lib/research/recent';
  import { renderBriefBody, type FactProvenance } from '$lib/research/render-brief-body';

  import type { PageData } from './$types';

  type FactRow = FactTimelineRow;

  let { data }: { data: PageData } = $props();

  // Slice `research-tab-ui`: record this visited symbol into the
  // landing-page's recent-symbols localStorage list. SSR-safe via
  // `readRecent` / `writeRecent`; pure dedupe-and-cap via
  // `recordRecent`. Nothing else in this file changes.
  const RECENT_STORAGE_KEY = 'iguanatrader.research.recent';
  $effect(() => {
    const symbol = data.symbol;
    if (!symbol) return;
    const next = recordRecent(readRecent(RECENT_STORAGE_KEY), symbol);
    writeRecent(RECENT_STORAGE_KEY, next);
  });

  let refreshing = $state(false);
  let refreshError = $state<string | null>(null);
  let currentBrief = $state(data.brief as Record<string, unknown> | null);
  let stats = $state<BriefStats | null>((data.stats as BriefStats | null) ?? null);

  async function loadStats(): Promise<void> {
    try {
      const res = await fetch(`/api/v1/research/stats/${encodeURIComponent(data.symbol)}`, {
        credentials: 'include'
      });
      if (!res.ok) return;
      stats = (await res.json()) as BriefStats;
    } catch {
      // Stat block is optional — quietly degrade.
    }
  }

  // Latest-mode facts come from server-side load; as-of mode swaps in
  // a client-side refetched list. `asOfInput` is the picker's bound
  // value; `appliedAsOf` is the value currently driving the displayed
  // facts (cleared when the picker is reset).
  let asOfInput = $state('');
  let appliedAsOf = $state<string | null>(null);
  let asOfFacts = $state<FactRow[] | null>(null);
  let asOfLoading = $state(false);
  let asOfError = $state<string | null>(null);

  let facts = $derived((asOfFacts ?? (data.facts as FactRow[])) as FactRow[]);

  async function applyAsOf(): Promise<void> {
    const raw = asOfInput.trim();
    if (!raw) {
      // Empty input → reset to latest mode.
      appliedAsOf = null;
      asOfFacts = null;
      asOfError = null;
      return;
    }
    asOfLoading = true;
    asOfError = null;
    try {
      const url = `/api/v1/research/facts/${encodeURIComponent(data.symbol)}?as_of=${encodeURIComponent(raw)}`;
      const res = await fetch(url, { credentials: 'include' });
      if (!res.ok) {
        const text = await res.text();
        asOfError = `as-of failed (${res.status}): ${text.slice(0, 200)}`;
        return;
      }
      asOfFacts = (await res.json()) as FactRow[];
      appliedAsOf = raw;
    } catch (err) {
      asOfError = err instanceof Error ? err.message : String(err);
    } finally {
      asOfLoading = false;
    }
  }

  function resetAsOf(): void {
    asOfInput = '';
    appliedAsOf = null;
    asOfFacts = null;
    asOfError = null;
  }

  // Build a fact-id → provenance lookup for the citation chip tooltips.
  //
  // Primary source: the brief's `resolved_citations` — server-resolved
  // against research_facts, complete and authoritative for every UUID
  // the brief body cites (including facts older than the top-50
  // returned by `/facts/{symbol}`). Without this the chip would
  // render `(unresolved)` for any fact outside the latest window.
  //
  // Fallback: the loaded `facts` list, so the tooltip still has data
  // when a chip is rendered from a context where only the facts list
  // is in scope (e.g. as-of-mode swaps in a different fact set).
  let factById = $derived.by(() => {
    const map = new Map<string, FactProvenance>();
    for (const f of facts) {
      map.set(f.id, f);
    }
    const resolved = currentBrief?.resolved_citations as
      | Array<{
          fact_id: string;
          source_id?: string;
          source_url?: string | null;
          retrieval_method?: FactProvenance['retrieval_method'];
          retrieved_at?: string | null;
          fact_kind?: string;
          value_excerpt?: string;
        }>
      | undefined;
    if (resolved) {
      for (const r of resolved) {
        map.set(r.fact_id, {
          id: r.fact_id,
          source_id: r.source_id,
          source_url: r.source_url ?? null,
          retrieval_method: r.retrieval_method ?? null,
          retrieved_at: r.retrieved_at ?? null,
          fact_kind: r.fact_kind,
          value_excerpt: r.value_excerpt
        });
      }
    }
    return map;
  });

  let body = $derived(
    (currentBrief?.body_markdown as string | undefined) ??
      (currentBrief?.thesis_text as string | undefined) ??
      ''
  );
  let renderedHtml = $derived(renderBriefBody(body, factById));
  let auditTrailVersion = $derived((currentBrief?.version as number | undefined) ?? null);

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
      // Stats are derived from the same facts the LLM read — refresh
      // them too so the operator's snapshot is consistent with the
      // brief they just re-synthesised.
      void loadStats();
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

    {#if stats}
      <StatBlock {stats} />
    {/if}

    <article class="brief-body" aria-label="Brief summary">
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
      {@html renderedHtml}
    </article>

    {#if auditTrailVersion !== null}
      <p class="audit-link">
        <a href="/research/{data.symbol}/audit-trail/{auditTrailVersion}"
          >View audit trail (FR70 derivation chain) →</a
        >
      </p>
    {/if}
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

  <section class="as-of-controls" aria-label="As-of date picker">
    <label for="as-of-input">As-of (UTC):</label>
    <input
      id="as-of-input"
      type="datetime-local"
      bind:value={asOfInput}
      step="1"
      disabled={asOfLoading}
    />
    <button type="button" onclick={applyAsOf} disabled={asOfLoading}>
      {asOfLoading ? 'Loading…' : 'Apply'}
    </button>
    {#if appliedAsOf}
      <button type="button" class="reset" onclick={resetAsOf} disabled={asOfLoading}>
        Reset to latest
      </button>
    {/if}
    {#if asOfError}
      <span role="alert" class="error">{asOfError}</span>
    {/if}
  </section>

  <FactTimeline {facts} asOf={appliedAsOf} />
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
    font-family: var(--font-sans, sans-serif);
    background: var(--surface);
    padding: 1rem;
    border-radius: 4px;
    line-height: 1.55;
  }
  .brief-body :global(h1),
  .brief-body :global(h2),
  .brief-body :global(h3),
  .brief-body :global(h4) {
    margin: 0.75rem 0 0.5rem;
    color: var(--ink);
  }
  .brief-body :global(p) {
    margin: 0.5rem 0;
  }
  .brief-body :global(ul),
  .brief-body :global(ol) {
    margin: 0.5rem 0 0.5rem 1.25rem;
  }
  .brief-body :global(a) {
    color: var(--accent);
  }
  .brief-body :global(code) {
    font-family: monospace;
    background: var(--surface-hover, rgba(0, 0, 0, 0.05));
    padding: 0.05rem 0.25rem;
    border-radius: 3px;
  }
  .brief-body :global(.citation-sup) {
    line-height: 0;
    margin-left: 1px;
  }
  .brief-body :global(.citation-ref) {
    text-decoration: none;
    color: var(--accent);
    font-size: 0.7em;
    font-weight: 600;
    padding: 0 0.1em;
    vertical-align: super;
  }
  .brief-body :global(.citation-ref:hover) {
    text-decoration: underline;
  }
  .brief-body :global(.citation-ref-broken) {
    color: var(--warn-fg, #960);
    cursor: help;
  }
  .brief-body :global(.brief-references) {
    margin-top: 1.5rem;
    padding-top: 1rem;
    border-top: 1px solid var(--mute);
  }
  .brief-body :global(.brief-references h3) {
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--mute);
    margin: 0 0 0.5rem;
  }
  .brief-body :global(.references-list) {
    margin: 0;
    padding-left: 1.5rem;
    font-size: 12px;
    color: var(--mute);
    line-height: 1.6;
  }
  .brief-body :global(.references-list li) {
    margin: 0.15rem 0;
  }
  .brief-body :global(.references-list .ref-back) {
    color: var(--accent);
    text-decoration: none;
    margin-right: 0.4rem;
  }
  .brief-body :global(.references-list .ref-back:hover) {
    text-decoration: underline;
  }
  .brief-body :global(.references-list .ref-text) {
    color: var(--ink);
  }
  .brief-body :global(.references-list .ref-meta) {
    color: var(--mute);
    margin-left: 0.4rem;
  }
  .brief-body :global(.references-list .ref-link) {
    margin-left: 0.4rem;
    color: var(--accent);
    text-decoration: none;
    font-weight: 500;
  }
  .brief-body :global(.references-list .ref-link:hover) {
    text-decoration: underline;
  }
  .brief-body :global(.references-list .ref-item-broken) {
    color: var(--warn-fg, #960);
  }
  .brief-body :global(.references-list :target) {
    background: var(--surface-hover, rgba(0, 0, 0, 0.08));
    border-radius: 3px;
    padding: 0 0.25rem;
  }
  .as-of-controls {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 1rem 0 0.5rem;
    font-size: 13px;
    color: var(--mute);
  }
  .as-of-controls input {
    font-family: monospace;
    padding: 0.25rem 0.4rem;
    border: 1px solid var(--mute);
    border-radius: 3px;
    background: var(--surface);
    color: var(--ink);
  }
  .as-of-controls button {
    padding: 0.25rem 0.6rem;
    font-size: 12px;
  }
  .as-of-controls .reset {
    background: transparent;
    color: var(--mute);
    border: 1px solid var(--mute);
  }
  .audit-link {
    margin: 0.5rem 0 1rem;
  }
  .audit-link a {
    color: var(--accent);
    text-decoration: none;
    font-size: 13px;
  }
  .audit-link a:hover {
    text-decoration: underline;
  }
</style>
