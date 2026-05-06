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

  let { data }: { data: PageData } = $props();

  let refreshing = $state(false);
  let refreshError = $state<string | null>(null);
  let currentBrief = $state(data.brief as Record<string, unknown> | null);

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
  <header>
    <h1>Research — {data.symbol}</h1>
    <button type="button" onclick={refresh} disabled={refreshing}>
      {refreshing ? 'Synthesising…' : 'Refresh brief'}
    </button>
  </header>

  {#if refreshError}
    <div role="alert" class="error">{refreshError}</div>
  {/if}

  {#if currentBrief}
    <article aria-label="Brief summary">
      <h2>
        Brief v{(currentBrief.version as number) ?? '–'} ·
        <span class="methodology">{currentBrief.methodology}</span>
      </h2>
      {#if currentBrief.partial}
        <div role="status" class="warn">Partial brief — required tier-A features missing.</div>
      {/if}
      <pre class="markdown">{currentBrief.body_markdown ?? currentBrief.thesis_text}</pre>
    </article>
  {:else}
    <article aria-label="No brief yet">
      <p>No brief synthesised yet for {data.symbol}.</p>
      <p>Click <strong>Refresh brief</strong> to run the methodology pipeline.</p>
    </article>
  {/if}

  <section aria-label="Recent facts">
    <h2>Recent facts ({(data.facts as unknown[]).length})</h2>
    {#if (data.facts as unknown[]).length === 0}
      <p>No facts ingested yet for {data.symbol}.</p>
    {:else}
      <ul>
        {#each data.facts as fact (((fact as Record<string, unknown>).id as string))}
          {@const f = fact as Record<string, unknown>}
          <li>
            <span class="fact-kind">{f.fact_kind}</span>
            <span class="fact-source">{f.source_id}</span>
            <span class="fact-value">{f.value_numeric ?? f.value_text ?? ''}</span>
            <time datetime={f.effective_from as string}>{f.effective_from}</time>
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
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
  }
  h2 {
    font-size: 18px;
    font-weight: 600;
    margin-top: 1rem;
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
  .methodology {
    color: var(--mute);
    font-weight: 400;
  }
  pre.markdown {
    white-space: pre-wrap;
    word-wrap: break-word;
    font-family: var(--font-sans, sans-serif);
    background: var(--surface);
    padding: 1rem;
    border-radius: 4px;
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
