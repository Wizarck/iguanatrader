/**
 * Slice research-frontend-extras §4 — parse citation markers from
 * brief markdown text.
 *
 * The brief body comes from R5 synthesis with inline citation markers
 * of the form ``[fact:<uuid>]``. v1 ships a hand-rolled marker
 * splitter (no marked / DOMPurify deps) — the brief body remains
 * plain text but every marker is replaced by a mounted CitationLink
 * component at the correct DOM offset.
 *
 * Output is an alternating sequence of ``{ kind: 'text'; value }`` and
 * ``{ kind: 'citation'; factId }`` segments. The Svelte page iterates
 * the array and renders each segment with the appropriate component
 * (text → ``<span>``, citation → ``<CitationLink>``).
 */

export type TextSegment = { kind: 'text'; value: string };
export type CitationSegment = { kind: 'citation'; factId: string };
export type BriefSegment = TextSegment | CitationSegment;

const CITATION_RE = /\[fact:([0-9a-fA-F-]{36})\]/g;

export function parseCitations(text: string): BriefSegment[] {
  const segments: BriefSegment[] = [];
  let lastIndex = 0;
  for (const match of text.matchAll(CITATION_RE)) {
    const start = match.index ?? 0;
    if (start > lastIndex) {
      segments.push({
        kind: 'text',
        value: text.slice(lastIndex, start)
      });
    }
    segments.push({ kind: 'citation', factId: match[1] });
    lastIndex = start + match[0].length;
  }
  if (lastIndex < text.length) {
    segments.push({ kind: 'text', value: text.slice(lastIndex) });
  }
  return segments;
}
