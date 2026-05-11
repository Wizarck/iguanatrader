<script lang="ts" module>
  export const meta = {
    label: 'Audit trail',
    icon: 'file-search',
    order: 42,
    hidden: true
  } as const;
</script>

<script lang="ts">
  import { page } from '$app/state';

  import AuditTrailViewer, {
    type AuditTrailEntry,
    type AuditTrailViewerFactRow
  } from '$lib/components/research/AuditTrailViewer.svelte';
  import BriefHeader from '$lib/components/research/BriefHeader.svelte';

  import type { PageData } from './$types';

  type FactRow = AuditTrailViewerFactRow & {
    fact_kind?: string;
  };

  let { data }: { data: PageData } = $props();

  let brief = $derived(data.brief as Record<string, unknown>);
  let entries = $derived((brief.audit_trail as AuditTrailEntry[] | undefined) ?? []);
  let facts = $derived(data.facts as FactRow[]);

  let factById = $derived.by(() => {
    const map = new Map<string, FactRow>();
    for (const f of facts) {
      map.set(f.id, f);
    }
    return map;
  });

  let deepLinkIndex = $derived.by(() => {
    const raw = page.url.searchParams.get('entry');
    if (raw === null) return null;
    const n = Number.parseInt(raw, 10);
    return Number.isFinite(n) && n >= 0 && n < entries.length ? n : null;
  });
</script>

<svelte:head>
  <title>Audit trail · {data.symbol} v{data.requestedVersion} · iguanatrader</title>
</svelte:head>

<section>
  <nav class="crumbs">
    <a href="/research/{data.symbol}">← Back to {data.symbol} brief</a>
  </nav>

  <BriefHeader
    symbol={data.symbol}
    methodology={(brief.methodology as string) ?? 'unknown'}
    version={(brief.version as number) ?? 0}
    synthesizedAt={(brief.created_at as string) ?? null}
    refreshing={false}
    refreshError={null}
    onRefresh={() => {}}
    refreshDisabled={true}
  />

  <h2>Audit trail · {entries.length} entries</h2>
  <p class="hint">
    Every numeric output in this brief is reproducible from the recorded formula + inputs +
    intermediate steps + final output (FR70). Click an entry to expand its derivation.
  </p>

  <AuditTrailViewer {entries} {factById} {deepLinkIndex} />
</section>

<style>
  section {
    color: var(--ink);
    padding: 1rem;
  }
  .crumbs {
    margin-bottom: 1rem;
    font-size: 13px;
  }
  .crumbs a {
    color: var(--accent);
    text-decoration: none;
  }
  .crumbs a:hover {
    text-decoration: underline;
  }
  h2 {
    font-size: 18px;
    font-weight: 600;
    margin: 1.25rem 0 0.25rem;
  }
  .hint {
    color: var(--mute);
    font-size: 13px;
    margin: 0 0 0.75rem;
  }
</style>
