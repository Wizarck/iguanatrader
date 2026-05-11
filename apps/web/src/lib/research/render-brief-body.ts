/**
 * Markdown → sanitized HTML pipeline for research brief bodies.
 *
 * Two-stage:
 *
 *   1. `marked` parses the markdown to raw HTML (with GFM + linebreaks).
 *      Configured with `async: false` so the helper stays synchronous
 *      (Svelte template expressions don't await).
 *   2. `isomorphic-dompurify` sanitizes the HTML against a strict
 *      allow-list. We sanitize *after* marked so the same pipeline works
 *      whether the markdown source is operator-written or LLM-generated.
 *
 * Citation markers (`[fact:<uuid>]`) survive both stages untouched —
 * marked treats them as literal text, DOMPurify is text-pass-through.
 * The page renderer splits on the marker pattern with `parseCitations`
 * before injecting via `{@html}`.
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

const ALLOWED_ATTR = ['href', 'class', 'data-fact-id', 'title'];

export function renderBriefBody(markdownText: string): string {
  if (!markdownText) return '';
  const rawHtml = marked.parse(markdownText, {
    async: false,
    breaks: true,
    gfm: true
  }) as string;
  return DOMPurify.sanitize(rawHtml, {
    USE_PROFILES: { html: true },
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOW_DATA_ATTR: true
  });
}
