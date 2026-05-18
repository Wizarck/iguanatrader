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

describe('renderBriefBody — Wikipedia-style numbered citations', () => {
  const FACT_A = '00000000-0000-0000-0000-00000000000a';
  const FACT_B = '00000000-0000-0000-0000-00000000000b';

  function _map(entries: Array<[string, FactProvenance]>): Map<string, FactProvenance> {
    return new Map(entries);
  }

  it('replaces each marker with a superscript [N] linking to the references list', () => {
    const html = renderBriefBody(
      `evidence per [fact:${FACT_A}].`,
      _map([
        [
          FACT_A,
          {
            source_id: 'EDGAR 10-Q',
            source_url: 'https://edgar.test/10q',
            fact_kind: 'fundamentals',
            value_excerpt: 'forward_pe=32.74',
            retrieval_method: 'api',
            retrieved_at: '2026-05-01T00:00:00Z'
          }
        ]
      ])
    );
    // Inline marker: <sup><a class="citation-ref" href="#cite-1" ...>[1]</a></sup>
    expect(html).toMatch(/<sup [^>]*class="citation-sup"[^>]*>/);
    expect(html).toMatch(/<a [^>]*class="citation-ref"[^>]*href="#cite-1"[^>]*>\[1\]<\/a>/);
    expect(html).toContain('data-fact-id="' + FACT_A + '"');
    // References section at the end with the matching <li id="cite-1">.
    expect(html).toMatch(/<section [^>]*class="brief-references"[^>]*>/);
    expect(html).toMatch(/<li [^>]*id="cite-1"[^>]*>/);
    // Label uses friendly fact_kind + value excerpt.
    expect(html).toContain('fundamentals · forward_pe=32.74');
    // External link rendered for publicly-reachable URL.
    expect(html).toContain('href="https://edgar.test/10q"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('view source ↗');
  });

  it('repeated citations of the same fact reuse the same number', () => {
    const html = renderBriefBody(
      `first [fact:${FACT_A}] and again [fact:${FACT_A}].`,
      _map([
        [
          FACT_A,
          {
            source_id: 'EDGAR',
            source_url: 'https://edgar.test/10q',
            fact_kind: 'fundamentals'
          }
        ]
      ])
    );
    // Two inline markers, both pointing at #cite-1.
    const hrefs = html.match(/href="#cite-\d+"/g) ?? [];
    expect(hrefs).toHaveLength(2);
    expect(hrefs[0]).toBe('href="#cite-1"');
    expect(hrefs[1]).toBe('href="#cite-1"');
    // Only one entry in the references list.
    const liMatches = html.match(/<li [^>]*id="cite-\d+"/g) ?? [];
    expect(liMatches).toHaveLength(1);
  });

  it('numbers citations in order of first appearance', () => {
    const html = renderBriefBody(
      `A [fact:${FACT_A}] B [fact:${FACT_B}] A again [fact:${FACT_A}].`,
      _map([
        [FACT_A, { source_id: 'A', fact_kind: 'fundamentals' }],
        [FACT_B, { source_id: 'B', fact_kind: 'analyst_ratings' }]
      ])
    );
    // First marker → [1], second → [2], third (same as first) → [1].
    const markerNumbers = [...html.matchAll(/<a [^>]*class="citation-ref"[^>]*>\[(\d+)\]<\/a>/g)].map(
      (m) => m[1]
    );
    expect(markerNumbers).toEqual(['1', '2', '1']);
  });

  it('emits the References section with a back-link arrow on each item', () => {
    const html = renderBriefBody(
      `see [fact:${FACT_A}]`,
      _map([
        [
          FACT_A,
          {
            source_id: 'openbb-sidecar',
            source_url: 'http://openbb_sidecar:8765/v1/equity/fundamentals/NVDA',
            fact_kind: 'fundamentals',
            value_excerpt: 'forward_pe=32.74',
            retrieval_method: 'api',
            retrieved_at: '2026-05-15T00:00:00Z'
          }
        ]
      ])
    );
    // ↑ back-link points to the in-body marker id.
    expect(html).toContain('href="#cite-back-1"');
    // Meta line includes source + retrieval method + retrieved_at.
    expect(html).toContain('openbb-sidecar · via api · @ 2026-05-15T00:00:00Z');
  });

  it('does NOT render an external link when source_url is internal (openbb_sidecar)', () => {
    // The sidecar's hostname only resolves inside the docker network —
    // a browser anchor would 404 from the user's machine. The reference
    // entry still names the source so provenance is preserved.
    const html = renderBriefBody(
      `see [fact:${FACT_A}]`,
      _map([
        [
          FACT_A,
          {
            source_id: 'openbb-sidecar',
            source_url: 'http://openbb_sidecar:8765/v1/equity/fundamentals/AMD',
            fact_kind: 'fundamentals'
          }
        ]
      ])
    );
    // Inline ref is the <sup><a href="#cite-1"> (internal anchor — fine).
    // External "view source ↗" link MUST NOT appear for internal hosts.
    expect(html).not.toContain('view source');
    // And no anchor with the internal hostname.
    expect(html).not.toContain('http://openbb_sidecar:');
    expect(html).not.toContain('http://openbb-sidecar:');
    // But the source label is still visible to the reader.
    expect(html).toContain('openbb-sidecar');
  });

  it('renders broken-citation marker when fact is unresolved', () => {
    const html = renderBriefBody(`unresolved [fact:${FACT_A}]`);
    expect(html).toContain('citation-ref-broken');
    expect(html).toMatch(/<a [^>]*class="citation-ref citation-ref-broken"[^>]*>\[1\]<\/a>/);
    // References entry flags the gap.
    expect(html).toContain('Unresolved citation');
  });

  it('omits the References section entirely when there are no citations', () => {
    const html = renderBriefBody('Plain prose with no markers.');
    expect(html).not.toContain('brief-references');
    expect(html).not.toContain('References');
  });

  it('escapes HTML entities in fact metadata to prevent injection', () => {
    const html = renderBriefBody(
      `injection [fact:${FACT_A}]`,
      _map([
        [
          FACT_A,
          {
            source_id: 'evil<script>alert(1)</script>',
            source_url: "javascript:alert('x')",
            fact_kind: 'fundamentals'
          }
        ]
      ])
    );
    // Script tags + javascript: URLs are stripped. The label text
    // "alert(1)" surviving as inert prose is fine — there is no
    // executable context for it without the surrounding tags.
    expect(html.toLowerCase()).not.toContain('<script');
    expect(html.toLowerCase()).not.toContain('javascript:');
    // The literal `<` from the source_id was escaped, proving the
    // escape pipeline ran on the metadata before HTML assembly.
    expect(html).toContain('evil&lt;script&gt;');
  });

  it('preserves paragraph structure across multiple markers', () => {
    const html = renderBriefBody(
      `Strong quarter per [fact:${FACT_A}] and growing earnings per [fact:${FACT_B}].`,
      _map([
        [FACT_A, { source_id: 'A', source_url: 'https://a.test', fact_kind: 'fundamentals' }],
        [FACT_B, { source_id: 'B', source_url: 'https://b.test', fact_kind: 'fundamentals' }]
      ])
    );
    // Single <p> wraps the prose; the References section is a sibling
    // block, not nested inside the paragraph.
    const paragraphMatches = html.match(/<p>/g) ?? [];
    expect(paragraphMatches).toHaveLength(1);
    expect(html).toContain('Strong quarter per');
    expect(html).toContain('growing earnings per');
  });

  it('renders friendly fact_kind labels in the References list', () => {
    const html = renderBriefBody(
      `see [fact:${FACT_A}]`,
      _map([
        [
          FACT_A,
          {
            source_id: 'openbb-sidecar',
            source_url: 'http://openbb_sidecar:8765/v1/equity/prices/NVDA',
            fact_kind: 'historical_prices_window',
            value_excerpt: 'last=424.10 @ 2026-05-15'
          }
        ]
      ])
    );
    // `historical_prices_window` → `prices` in the references entry.
    expect(html).toContain('prices · last=424.10 @ 2026-05-15');
    expect(html).not.toMatch(/>historical_prices_window/);
  });
});
