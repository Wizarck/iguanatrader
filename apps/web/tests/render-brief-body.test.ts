/**
 * Unit tests for ``renderBriefBody`` — the marker pre-pass + marked +
 * DOMPurify pipeline.
 *
 * Invariants:
 *
 *   1. Markdown features (headings, lists, bold, code, links) render to
 *      their canonical HTML tags.
 *   2. Dangerous payloads (``<script>``, ``onerror``, ``javascript:``
 *      URLs) are stripped by DOMPurify before the HTML reaches the DOM.
 *   3. Citation markers ``[fact:<uuid>]`` are pre-replaced with inline
 *      chip HTML BEFORE marked runs, preserving block structure (a
 *      paragraph containing two citations renders as ONE ``<p>``, not
 *      three).
 *   4. Chip variants:
 *      - URL present → ``<a class="citation-chip" target="_blank" ...>``
 *      - No URL → ``<span class="citation-chip" ...>``
 *      - Unresolved (no provenance map entry) → broken-citation span
 */

import { describe, expect, it } from 'vitest';

import {
  renderBriefBody,
  type FactProvenance
} from '../src/lib/research/render-brief-body';

describe('renderBriefBody — markdown rendering', () => {
  it('returns empty string for empty input', () => {
    expect(renderBriefBody('')).toBe('');
  });

  it('renders headings', () => {
    const html = renderBriefBody('## Thesis');
    expect(html).toContain('<h2');
    expect(html).toContain('Thesis');
  });

  it('renders unordered lists', () => {
    const html = renderBriefBody('- one\n- two');
    expect(html).toContain('<ul>');
    expect(html).toContain('<li>one</li>');
    expect(html).toContain('<li>two</li>');
  });

  it('renders inline code', () => {
    const html = renderBriefBody('use `marked` for parsing');
    expect(html).toContain('<code>marked</code>');
  });

  it('renders bold + emphasis', () => {
    const html = renderBriefBody('**bold** and _em_');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<em>em</em>');
  });
});

describe('renderBriefBody — sanitization', () => {
  it('strips <script> tags', () => {
    const html = renderBriefBody('safe <script>alert(1)</script> tail');
    expect(html.toLowerCase()).not.toContain('<script');
    expect(html.toLowerCase()).not.toContain('alert(1)');
  });

  it('strips inline event handler attributes', () => {
    const html = renderBriefBody('<img src="x" onerror="alert(1)">');
    expect(html.toLowerCase()).not.toContain('onerror');
    expect(html.toLowerCase()).not.toContain('alert(1)');
  });

  it('strips javascript: URLs from anchor href', () => {
    const html = renderBriefBody('[click](javascript:alert(1))');
    expect(html.toLowerCase()).not.toContain('javascript:');
  });

  it('drops disallowed tags (e.g. <iframe>)', () => {
    const html = renderBriefBody('<iframe src="https://evil.test"></iframe>');
    expect(html.toLowerCase()).not.toContain('<iframe');
  });
});

describe('renderBriefBody — citation chip inlining', () => {
  const FACT_A = '00000000-0000-0000-0000-00000000000a';
  const FACT_B = '00000000-0000-0000-0000-00000000000b';

  function _map(entries: Array<[string, FactProvenance]>): Map<string, FactProvenance> {
    return new Map(entries);
  }

  it('renders an anchor chip when source_url is present', () => {
    const html = renderBriefBody(
      `evidence per [fact:${FACT_A}].`,
      _map([
        [
          FACT_A,
          {
            source_id: 'EDGAR 10-Q',
            source_url: 'https://edgar.test/10q',
            retrieval_method: 'api',
            retrieved_at: '2026-05-01T00:00:00Z'
          }
        ]
      ])
    );
    expect(html).toMatch(/<a [^>]*class="citation-chip"[^>]*>/);
    expect(html).toContain('href="https://edgar.test/10q"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('data-fact-id="' + FACT_A + '"');
    expect(html).toContain('EDGAR 10-Q');
  });

  it('renders a span chip when no source_url', () => {
    const html = renderBriefBody(
      `see [fact:${FACT_A}]`,
      _map([[FACT_A, { source_id: 'manual entry' }]])
    );
    expect(html).toMatch(/<span [^>]*class="citation-chip"[^>]*>/);
    expect(html).not.toContain('<a ');
    expect(html).toContain('manual entry');
  });

  it('renders broken-citation chip when fact is unresolved', () => {
    const html = renderBriefBody(`unresolved [fact:${FACT_A}]`);
    expect(html).toContain('citation-chip-broken');
    expect(html).toContain('[fact:' + FACT_A.slice(0, 8) + ']');
  });

  it('preserves paragraph structure across multiple inline chips', () => {
    const html = renderBriefBody(
      `Strong quarter per [fact:${FACT_A}] and growing earnings per [fact:${FACT_B}].`,
      _map([
        [FACT_A, { source_id: 'A', source_url: 'https://a.test' }],
        [FACT_B, { source_id: 'B', source_url: 'https://b.test' }]
      ])
    );
    // Single <p> wraps the whole sentence (no split-paragraph artifact).
    const paragraphMatches = html.match(/<p>/g) ?? [];
    expect(paragraphMatches).toHaveLength(1);
    expect(html).toContain('Strong quarter per');
    expect(html).toContain('growing earnings per');
  });

  it('escapes HTML entities in fact metadata to prevent injection', () => {
    const html = renderBriefBody(
      `injection [fact:${FACT_A}]`,
      _map([
        [
          FACT_A,
          {
            source_id: 'evil<script>alert(1)</script>',
            source_url: "javascript:alert('x')"
          }
        ]
      ])
    );
    expect(html.toLowerCase()).not.toContain('<script');
    expect(html.toLowerCase()).not.toContain('javascript:');
  });
});
