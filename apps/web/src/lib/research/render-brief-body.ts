/**
 * Markdown → sanitized HTML pipeline for research brief bodies.
 *
 * Three-stage:
 *
 *   1. Pre-pass: replace each `[fact:<uuid>]` citation marker with inline
 *      citation chip HTML using the optional ``factById`` provenance map.
 *      Anchors when a ``source_url`` is present, spans otherwise. Unresolved
 *      markers render as broken-citation chips so operators see the gap.
 *   2. ``marked`` parses the full body (with chips inlined) to HTML in a
 *      single invocation. Block structure (paragraphs, headings, lists) is
 *      preserved correctly because the chips sit inside the surrounding
 *      block context rather than splitting it.
 *   3. ``isomorphic-dompurify`` sanitizes against a strict allow-list. The
 *      chip's ``target='_blank'``, ``rel`` + ``data-fact-id`` attributes
 *      survive thanks to the extended ALLOWED_ATTR list.
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
  'hr'
];

const ALLOWED_ATTR = ['href', 'class', 'data-fact-id', 'title', 'rel'];
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
};

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function buildTooltip(factId: string, fact: FactProvenance | undefined): string {
  if (!fact) return `[fact:${factId.slice(0, 8)}] (unresolved)`;
  const parts: string[] = [];
  if (fact.source_id) parts.push(fact.source_id);
  if (fact.retrieval_method) parts.push(`via ${fact.retrieval_method}`);
  if (fact.retrieved_at) parts.push(`@ ${fact.retrieved_at}`);
  return parts.length > 0 ? parts.join(' · ') : `[fact:${factId.slice(0, 8)}]`;
}

function renderCitationChip(factId: string, fact: FactProvenance | undefined): string {
  const shortId = factId.slice(0, 8);
  const label = fact?.source_id ?? `[fact:${shortId}]`;
  const title = buildTooltip(factId, fact);
  const safeFactId = escapeHtml(factId);
  const safeLabel = escapeHtml(label);
  const safeTitle = escapeHtml(title);

  if (fact?.source_url) {
    return (
      `<a class="citation-chip" href="${escapeHtml(fact.source_url)}" ` +
      `target="_blank" rel="noopener noreferrer" ` +
      `data-fact-id="${safeFactId}" title="${safeTitle}">${safeLabel}</a>`
    );
  }
  const brokenClass = fact ? 'citation-chip' : 'citation-chip citation-chip-broken';
  return (
    `<span class="${brokenClass}" data-fact-id="${safeFactId}" ` +
    `title="${safeTitle}">${safeLabel}</span>`
  );
}

export function renderBriefBody(
  markdownText: string,
  factById?: Map<string, FactProvenance>
): string {
  if (!markdownText) return '';
  // Step 1: marker pre-pass — replace [fact:<uuid>] with inline chip HTML.
  const withChips = markdownText.replace(CITATION_RE, (_, factId: string) =>
    renderCitationChip(factId, factById?.get(factId))
  );
  // Step 2: markdown → raw HTML.
  const rawHtml = marked.parse(withChips, {
    async: false,
    breaks: true,
    gfm: true
  }) as string;
  // Step 3: sanitize.
  return DOMPurify.sanitize(rawHtml, {
    USE_PROFILES: { html: true },
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ADD_ATTR,
    ALLOW_DATA_ATTR: true
  });
}
