<script lang="ts">
  // Slice research-frontend-extras §4.3 — inline citation chip.
  //
  // Lookup data (sourceLabel + retrievedAt + method) is resolved by the
  // parent page from `/api/v1/research/facts/{symbol}` and passed in as
  // props. When `factId` is unknown (broken citation), renders as warn
  // chip per components.md §4.3 edge case.

  type Method = 'api' | 'scrape' | 'manual' | 'llm';

  type Props = {
    factId: string;
    sourceLabel: string | null;
    sourceUrl: string | null;
    retrievedAt: string | null; // ISO 8601 UTC
    method: Method | null;
  };

  let { factId, sourceLabel, sourceUrl, retrievedAt, method }: Props = $props();

  let broken = $derived(sourceLabel === null || sourceUrl === null);

  function shortId(id: string): string {
    return id.slice(0, 8);
  }

  let displayLabel = $derived(broken ? `[broken:${shortId(factId)}]` : sourceLabel);
  let tooltip = $derived(
    broken
      ? `Broken citation for fact ${shortId(factId)} — the brief references a fact that could not be resolved.`
      : `Citation: ${sourceLabel} · retrieved ${retrievedAt} · via ${method}`
  );
  let ariaLabel = $derived(
    broken
      ? `Broken citation: fact ${factId}`
      : `Citation: ${sourceLabel} retrieved ${retrievedAt}`
  );
</script>

{#if broken}
  <span class="chip warn" title={tooltip} aria-label={ariaLabel} role="mark">
    {displayLabel}
  </span>
{:else if sourceUrl}
  <a
    class="chip"
    href={sourceUrl}
    target="_blank"
    rel="noopener noreferrer"
    title={tooltip}
    aria-label={ariaLabel}
  >
    {displayLabel}
  </a>
{/if}

<style>
  .chip {
    display: inline-flex;
    align-items: center;
    padding: 0 6px;
    margin: 0 2px;
    border-radius: 4px;
    background: var(--accent, oklch(70% 0.13 240));
    color: var(--accent-fg, white);
    font-size: 11px;
    font-weight: 500;
    line-height: 1.6;
    text-decoration: none;
    vertical-align: super;
    transition: background-color 0.1s ease-in-out;
  }
  .chip:hover {
    background: var(--accent-hover, oklch(60% 0.15 240));
  }
  .chip:visited {
    background: var(--accent, oklch(70% 0.13 240));
    opacity: 0.7;
  }
  .chip.warn {
    background: var(--warn-bg, oklch(80% 0.13 60));
    color: var(--warn-fg, oklch(30% 0.13 60));
  }
</style>
