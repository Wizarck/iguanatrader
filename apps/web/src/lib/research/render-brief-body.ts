/**
 * Markdown → sanitized HTML pipeline for research brief bodies.
 *
 * Citations follow the Wikipedia footnote pattern: each `[fact:<uuid>]`
 * marker in the prose renders as a small superscript `[N]` link, and a
 * single ``References`` section is appended to the end of the brief
 * with the full provenance for each cited fact (label, value, source,
 * retrieval method, retrieved_at, external link when publicly reachable).
 *
 * Why footnotes over inline chips: the LLM-written prose already
 * carries the numeric value (``P/E of 32.74x``); an inline chip that
 * repeats the same number is visual noise that competes with the
 * sentence. A subtle superscript points to verifiable provenance
 * without breaking reading rhythm.
 *
 * Pipeline:
 *   1. Pre-pass: walk markers in order of first appearance, assign
 *      monotonic numbers, replace each marker with
 *      ``<sup><a class="citation-ref" href="#cite-N">[N]</a></sup>``.
 *      Repeated citations of the same fact reuse the same number.
 *   2. Append a ``<section class="brief-references">`` listing each
 *      unique cited fact.
 *   3. ``marked`` parses the body+refs concatenation in one call so
 *      block structure survives.
 *   4. ``isomorphic-dompurify`` sanitizes against a strict allow-list.
 */
import DOMPurify from 'isomorphic-dompurify';
import { marked } from 'marked';

const ALLOWED_TAGS = [
  'p',
  'strong',
  'em',
  'h1',
  'h2',
  'h3',
  'h4',
  'ul',
  'ol',
  'li',
  'a',
  'code',
  'pre',
  'blockquote',
  'br',
  'span',
  'sup',
  'section',
  'hr'
];

const ALLOWED_ATTR = ['href', 'class', 'data-fact-id', 'title', 'rel', 'id', 'aria-label'];
// DOMPurify strips ``target`` by default (tab-nabbing safety). Allow it
// explicitly so the citation chip can open the source URL in a new tab;
// our chip HTML always pairs ``target="_blank"`` with
// ``rel="noopener noreferrer"``.
const ADD_ATTR = ['target'];

const CITATION_RE = /\[fact:([0-9a-fA-F-]{36})\]/g;

export type FactProvenance = {
  id?: string;
  source_id?: string;
  source_url?: string | null;
  retrieval_method?: 'api' | 'scrape' | 'manual' | 'llm' | null;
  retrieved_at?: string | null;
  fact_kind?: string;
  value_excerpt?: string;
};

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Friendly display labels for fact_kind. The raw snake_case
// (`historical_prices_window`, `analyst_ratings`) reads as schema-leak
// in inline prose AND in the References list. We map the common kinds
// to short human labels; unknown kinds fall back to spaced-lowercase.
const FACT_KIND_DISPLAY: Record<string, string> = {
  historical_prices_window: 'prices',
  analyst_ratings: 'analysts',
  fundamentals: 'fundamentals',
  news_sentiment: 'news',
  esg_score: 'ESG',
  eps_growth_yoy: 'EPS growth',
  revenue_growth_yoy: 'revenue growth',
  earnings_surprises: 'earnings',
  options_skew: 'options'
};

function prettyFactKind(kind: string): string {
  if (FACT_KIND_DISPLAY[kind]) return FACT_KIND_DISPLAY[kind];
  // `some_snake_kind` → `some snake kind`.
  return kind.replace(/_/g, ' ');
}

// Hostnames that resolve only inside the docker-compose / k8s network.
// We must NOT emit anchors pointing at these — the user's browser will
// never reach them. The References entry still shows the source label
// + retrieval method so the reader knows where the data came from.
const INTERNAL_HOST_PREFIXES = [
  'http://openbb_sidecar:',
  'http://openbb-sidecar:',
  'http://api:',
  'http://web:'
];

function isPubliclyReachable(url: string): boolean {
  return !INTERNAL_HOST_PREFIXES.some((prefix) => url.startsWith(prefix));
}

function buildTooltip(factId: string, fact: FactProvenance | undefined): string {
  if (!fact) return `[fact:${factId.slice(0, 8)}] (unresolved)`;
  const parts: string[] = [];
  if (fact.fact_kind) {
    parts.push(
      fact.value_excerpt ? `${fact.fact_kind}: ${fact.value_excerpt}` : fact.fact_kind
    );
  } else if (fact.value_excerpt) {
    parts.push(fact.value_excerpt);
  }
  if (fact.source_id) parts.push(fact.source_id);
  if (fact.retrieval_method) parts.push(`via ${fact.retrieval_method}`);
  if (fact.retrieved_at) parts.push(`@ ${fact.retrieved_at}`);
  return parts.length > 0 ? parts.join(' · ') : `[fact:${factId.slice(0, 8)}]`;
}

function renderRefMarker(n: number, factId: string, fact: FactProvenance | undefined): string {
  // Wikipedia-style superscript footnote. The href jumps to the
  // matching <li id="cite-N"> in the references section below.
  const safeFactId = escapeHtml(factId);
  const safeTitle = escapeHtml(buildTooltip(factId, fact));
  const brokenClass = fact ? 'citation-ref' : 'citation-ref citation-ref-broken';
  return (
    `<sup class="citation-sup">` +
    `<a class="${brokenClass}" href="#cite-${n}" ` +
    `id="cite-back-${n}" data-fact-id="${safeFactId}" title="${safeTitle}">` +
    `[${n}]</a></sup>`
  );
}

type CitationEntry = {
  n: number;
  factId: string;
  fact: FactProvenance | undefined;
};

function renderReferencesSection(entries: CitationEntry[]): string {
  if (entries.length === 0) return '';
  const items = entries.map((e) => renderReferenceItem(e)).join('');
  return (
    `<section class="brief-references" aria-label="References">` +
    `<h3>References</h3>` +
    `<ol class="references-list">${items}</ol>` +
    `</section>`
  );
}

function renderReferenceItem({ n, factId, fact }: CitationEntry): string {
  const back = `<a class="ref-back" href="#cite-back-${n}" aria-label="Back to citation">↑</a>`;
  if (!fact) {
    return (
      `<li id="cite-${n}" class="ref-item ref-item-broken">${back}` +
      `<span class="ref-text">Unresolved citation (fact ${escapeHtml(factId.slice(0, 8))})</span>` +
      `</li>`
    );
  }
  const labelParts: string[] = [];
  if (fact.fact_kind) labelParts.push(prettyFactKind(fact.fact_kind));
  if (fact.value_excerpt) labelParts.push(fact.value_excerpt);
  const label = labelParts.join(' · ') || `fact ${factId.slice(0, 8)}`;

  const metaParts: string[] = [];
  if (fact.source_id) metaParts.push(fact.source_id);
  if (fact.retrieval_method) metaParts.push(`via ${fact.retrieval_method}`);
  if (fact.retrieved_at) metaParts.push(`@ ${fact.retrieved_at}`);
  const meta = metaParts.length > 0 ? ` <span class="ref-meta">${escapeHtml(metaParts.join(' · '))}</span>` : '';

  let link = '';
  if (fact.source_url && isPubliclyReachable(fact.source_url)) {
    link =
      ` <a class="ref-link" href="${escapeHtml(fact.source_url)}" ` +
      `target="_blank" rel="noopener noreferrer">view source ↗</a>`;
  }

  return (
    `<li id="cite-${n}" class="ref-item">${back}` +
    `<span class="ref-text">${escapeHtml(label)}</span>${meta}${link}` +
    `</li>`
  );
}

export function renderBriefBody(
  markdownText: string,
  factById?: Map<string, FactProvenance>
): string {
  if (!markdownText) return '';

  // Pass 1: walk markers in order of first appearance, assign monotonic
  // numbers, swap each marker for a <sup>[N]</sup> link. Repeated
  // citations of the same fact_id reuse the same number.
  const entries: CitationEntry[] = [];
  const factIdToNumber = new Map<string, number>();
  const withRefs = markdownText.replace(CITATION_RE, (_, rawFactId: string) => {
    const factId = rawFactId.toLowerCase();
    let n = factIdToNumber.get(factId);
    const fact = factById?.get(factId) ?? factById?.get(rawFactId);
    if (n === undefined) {
      n = entries.length + 1;
      factIdToNumber.set(factId, n);
      entries.push({ n, factId, fact });
    }
    return renderRefMarker(n, factId, fact);
  });

  // Pass 2: append the References section.
  const refsHtml = renderReferencesSection(entries);

  // Pass 3: markdown → raw HTML. We append the refs HTML AFTER marked
  // so its <section><ol><li> structure isn't reformatted as nested
  // markdown lists.
  const bodyHtml = marked.parse(withRefs, {
    async: false,
    breaks: true,
    gfm: true
  }) as string;

  // Pass 4: sanitize.
  return DOMPurify.sanitize(bodyHtml + refsHtml, {
    USE_PROFILES: { html: true },
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ADD_ATTR,
    ALLOW_DATA_ATTR: true
  });
}
