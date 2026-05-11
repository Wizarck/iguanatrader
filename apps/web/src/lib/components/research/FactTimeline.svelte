<script lang="ts" module>
  /**
   * FactTimeline — chronological list of research facts (compact mode v1).
   *
   * Bitemporal "as-of" mode is deferred (would need a date picker + an
   * `?asOf=` query parameter on the `/facts/{symbol}` endpoint). Full
   * mode (per-fact expansion with raw JSON payload) is also deferred —
   * operators reach raw provenance via `/research/[symbol]/audit-trail/...`.
   */
  export type FactTimelineRow = {
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
</script>

<script lang="ts">
  type Props = {
    facts: FactTimelineRow[];
    maxItems?: number;
    highlightFactId?: string | null;
  };

  let { facts, maxItems = 20, highlightFactId = null }: Props = $props();

  const RETRIEVAL_ICON: Record<string, string> = {
    api: '↪',
    scrape: '⌬',
    manual: '✎',
    llm: '✦'
  };

  let sorted = $derived.by(() => {
    const copy = [...facts];
    copy.sort((a, b) => (b.effective_from ?? '').localeCompare(a.effective_from ?? ''));
    return copy.slice(0, maxItems);
  });

  function formatValue(f: FactTimelineRow): string {
    if (f.value_numeric !== null && f.value_numeric !== undefined) return String(f.value_numeric);
    return f.value_text ?? '';
  }
</script>

<section class="fact-timeline" aria-label="Recent facts timeline">
  <header>
    <h3>Recent facts</h3>
    <span class="count">{facts.length} total · showing {sorted.length}</span>
  </header>
  {#if sorted.length === 0}
    <p class="empty">No facts ingested yet.</p>
  {:else}
    <ol>
      {#each sorted as fact, idx (fact.id ?? idx)}
        <li class:highlight={fact.id === highlightFactId}>
          <time class="when" datetime={fact.effective_from ?? ''}>
            {fact.effective_from?.slice(0, 10) ?? '—'}
          </time>
          <span class="kind">{fact.fact_kind ?? '—'}</span>
          <span class="value">{formatValue(fact)}</span>
          <span class="method" title={fact.retrieval_method ?? 'unknown'}>
            {RETRIEVAL_ICON[fact.retrieval_method ?? ''] ?? '·'}
          </span>
          <span class="source">
            {#if fact.source_url}
              <a href={fact.source_url} target="_blank" rel="noopener noreferrer">
                {fact.source_id}
              </a>
            {:else}
              {fact.source_id}
            {/if}
          </span>
        </li>
      {/each}
    </ol>
  {/if}
</section>

<style>
  section {
    margin-top: 1.5rem;
  }
  header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 0.5rem;
  }
  h3 {
    font-size: 16px;
    font-weight: 600;
    color: var(--ink);
    margin: 0;
  }
  .count {
    font-size: 12px;
    color: var(--mute);
  }
  ol {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 0.25rem;
  }
  li {
    display: grid;
    grid-template-columns: 7rem 9rem 1fr 1.5rem 8rem;
    gap: 0.5rem;
    align-items: center;
    padding: 0.4rem 0.5rem;
    border-radius: 4px;
    background: var(--surface);
    font-size: 13px;
  }
  li.highlight {
    outline: 2px solid var(--accent);
  }
  .when {
    color: var(--mute);
    font-family: monospace;
  }
  .kind {
    color: var(--accent);
    font-family: monospace;
  }
  .value {
    color: var(--ink);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .method {
    text-align: center;
    color: var(--mute);
  }
  .source {
    color: var(--mute);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .source a {
    color: var(--accent);
    text-decoration: none;
  }
  .source a:hover {
    text-decoration: underline;
  }
  .empty {
    color: var(--mute);
    font-style: italic;
  }
</style>
