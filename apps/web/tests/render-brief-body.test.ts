/**
 * Unit tests for ``renderBriefBody`` — the marked + DOMPurify pipeline.
 *
 * The two invariants under test:
 *
 *   1. Markdown features (headings, lists, bold, code, links) render as
 *      their canonical HTML tags.
 *   2. Dangerous payloads (``<script>``, ``onerror``, ``javascript:``
 *      URLs) are stripped by DOMPurify before the HTML reaches the DOM.
 */

import { describe, expect, it } from 'vitest';

import { renderBriefBody } from '../src/lib/research/render-brief-body';

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

  it('preserves citation marker tokens verbatim', () => {
    const html = renderBriefBody('See [fact:abc-123] for evidence.');
    expect(html).toContain('[fact:abc-123]');
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
    // DOMPurify either drops the entire <img> (not in ALLOWED_TAGS) or
    // strips the onerror handler. Either way, no `onerror` survives.
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
