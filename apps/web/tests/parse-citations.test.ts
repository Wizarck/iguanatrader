/**
 * Boundary tests for ``parseCitations`` — the citation-marker splitter
 * consumed by both the brief detail page and the audit-trail page.
 */

import { describe, expect, it } from 'vitest';

import { parseCitations } from '../src/lib/research/parse-citations';

describe('parseCitations', () => {
  it('returns a single text segment for plain text', () => {
    const segs = parseCitations('no citations here');
    expect(segs).toHaveLength(1);
    expect(segs[0]).toEqual({ kind: 'text', value: 'no citations here' });
  });

  it('returns empty array for empty input', () => {
    expect(parseCitations('')).toEqual([]);
  });

  it('splits a single citation in the middle', () => {
    const segs = parseCitations('before [fact:00000000-0000-0000-0000-000000000001] after');
    expect(segs).toHaveLength(3);
    expect(segs[0]).toEqual({ kind: 'text', value: 'before ' });
    expect(segs[1]).toEqual({
      kind: 'citation',
      factId: '00000000-0000-0000-0000-000000000001'
    });
    expect(segs[2]).toEqual({ kind: 'text', value: ' after' });
  });

  it('handles a citation at the start', () => {
    const segs = parseCitations('[fact:00000000-0000-0000-0000-000000000002] starts here');
    expect(segs[0]).toEqual({
      kind: 'citation',
      factId: '00000000-0000-0000-0000-000000000002'
    });
  });

  it('handles a citation at the end', () => {
    const segs = parseCitations('ends with [fact:00000000-0000-0000-0000-000000000003]');
    expect(segs[segs.length - 1]).toEqual({
      kind: 'citation',
      factId: '00000000-0000-0000-0000-000000000003'
    });
  });

  it('handles multiple citations', () => {
    const segs = parseCitations(
      '[fact:00000000-0000-0000-0000-000000000004] and ' +
        '[fact:00000000-0000-0000-0000-000000000005] both'
    );
    const citations = segs.filter((s) => s.kind === 'citation');
    expect(citations).toHaveLength(2);
  });

  it('ignores malformed citation markers', () => {
    const segs = parseCitations('not [fact:not-a-uuid] valid');
    expect(segs).toHaveLength(1);
    expect(segs[0]).toEqual({ kind: 'text', value: 'not [fact:not-a-uuid] valid' });
  });
});
