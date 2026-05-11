<script lang="ts" module>
  /**
   * AuditTrailViewer — accordion of audit-trail entries (FR70 derivation chain).
   *
   * Each entry is one calculation: ``formula`` → ``inputs`` → ``intermediate_steps``
   * → ``final_output``. Inputs are clickable when the parent provides a
   * `factById` lookup (links into the same brief's recent-facts timeline).
   *
   * Deep linking: pass `deepLinkIndex` to scroll a specific entry into view
   * + auto-open its accordion. The brief-detail page wires this from
   * `?entry=<n>` query param.
   */
  export type AuditTrailEntry = {
    formula: string;
    inputs: Array<{ fact_id?: string; value?: number | string } | Record<string, unknown>>;
    intermediate_steps: string[];
    final_output: number | string;
  };

  export type AuditTrailViewerFactRow = {
    id: string;
    source_id?: string;
    fact_kind?: string;
  };
</script>

<script lang="ts">
  type Props = {
    entries: AuditTrailEntry[];
    factById?: Map<string, AuditTrailViewerFactRow> | null;
    deepLinkIndex?: number | null;
  };

  let { entries, factById = null, deepLinkIndex = null }: Props = $props();

  let openIndex = $state<number | null>(null);
  // Keep openIndex synced with deepLinkIndex when the parent updates the
  // URL query parameter (one-way; user clicks can still flip it).
  $effect(() => {
    openIndex = deepLinkIndex;
  });

  function toggle(idx: number): void {
    openIndex = openIndex === idx ? null : idx;
  }

  function isFactInput(
    input: { fact_id?: string; value?: number | string } | Record<string, unknown>
  ): input is { fact_id: string; value?: number | string } {
    return typeof (input as { fact_id?: unknown }).fact_id === 'string';
  }

  function factDescription(id: string): string {
    const f = factById?.get(id);
    if (!f) return id.slice(0, 8);
    if (f.fact_kind && f.source_id) return `${f.fact_kind} · ${f.source_id}`;
    return f.source_id ?? f.fact_kind ?? id.slice(0, 8);
  }
</script>

<section class="audit-trail" aria-label="Audit trail derivation chain">
  {#if entries.length === 0}
    <p class="empty">This brief has no recorded audit-trail entries.</p>
  {:else}
    <ol>
      {#each entries as entry, idx (idx)}
        <li id="audit-entry-{idx}" class:open={openIndex === idx}>
          <button
            type="button"
            class="head"
            aria-expanded={openIndex === idx}
            aria-controls="audit-body-{idx}"
            onclick={() => toggle(idx)}
          >
            <span class="formula">{entry.formula}</span>
            <span class="final">→ {entry.final_output}</span>
            <span class="caret" aria-hidden="true">{openIndex === idx ? '▾' : '▸'}</span>
          </button>
          {#if openIndex === idx}
            <div class="body" id="audit-body-{idx}">
              <dl>
                <dt>Inputs</dt>
                <dd>
                  {#if entry.inputs.length === 0}
                    <span class="mute">no inputs recorded</span>
                  {:else}
                    <ul class="inputs">
                      {#each entry.inputs as input, j (j)}
                        <li>
                          {#if isFactInput(input)}
                            <code class="fact">[fact:{input.fact_id.slice(0, 8)}]</code>
                            <span class="fact-desc">{factDescription(input.fact_id)}</span>
                            {#if input.value !== undefined}
                              <span class="value">= {input.value}</span>
                            {/if}
                          {:else}
                            <code class="raw">{JSON.stringify(input)}</code>
                          {/if}
                        </li>
                      {/each}
                    </ul>
                  {/if}
                </dd>
                <dt>Intermediate steps</dt>
                <dd>
                  {#if entry.intermediate_steps.length === 0}
                    <span class="mute">no intermediate steps recorded</span>
                  {:else}
                    <ol class="steps">
                      {#each entry.intermediate_steps as step, k (k)}
                        <li>{step}</li>
                      {/each}
                    </ol>
                  {/if}
                </dd>
                <dt>Final output</dt>
                <dd>
                  <code class="final-output">{entry.final_output}</code>
                </dd>
              </dl>
            </div>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</section>

<style>
  section {
    margin-top: 1rem;
  }
  ol {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 0.5rem;
  }
  li {
    border: 1px solid var(--mute);
    border-radius: 4px;
    background: var(--surface);
    overflow: hidden;
  }
  li.open {
    border-color: var(--accent);
  }
  .head {
    display: grid;
    grid-template-columns: 1fr auto 1.5rem;
    gap: 0.75rem;
    align-items: center;
    width: 100%;
    background: transparent;
    border: none;
    padding: 0.6rem 0.75rem;
    text-align: left;
    cursor: pointer;
    color: var(--ink);
    font-family: monospace;
    font-size: 13px;
  }
  .head:hover {
    background: var(--surface-hover, rgba(0, 0, 0, 0.04));
  }
  .formula {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .final {
    color: var(--accent);
    font-weight: 600;
  }
  .caret {
    color: var(--mute);
  }
  .body {
    padding: 0.5rem 0.75rem 0.75rem;
    border-top: 1px solid var(--mute);
    font-size: 13px;
  }
  dl {
    display: grid;
    grid-template-columns: 8rem 1fr;
    gap: 0.5rem 1rem;
    margin: 0;
  }
  dt {
    font-weight: 600;
    color: var(--mute);
  }
  dd {
    margin: 0;
  }
  .inputs,
  .steps {
    margin: 0;
    padding-left: 1.25rem;
    display: grid;
    gap: 0.25rem;
  }
  .fact {
    color: var(--accent);
    font-family: monospace;
  }
  .fact-desc {
    color: var(--mute);
    margin-left: 0.5rem;
  }
  .value {
    margin-left: 0.5rem;
    color: var(--ink);
  }
  .raw {
    font-family: monospace;
    color: var(--mute);
    font-size: 12px;
  }
  .final-output {
    background: var(--surface-hover, rgba(0, 0, 0, 0.04));
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
  }
  .mute {
    color: var(--mute);
    font-style: italic;
  }
  .empty {
    color: var(--mute);
    font-style: italic;
  }
</style>
