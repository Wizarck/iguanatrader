/**
 * Unit tests for parseRecommendation + stripRecommendationSection
 * (slice U3 — recommendation card).
 *
 * Pin the regex contract against the canonical three_pillar prompt
 * output shape so a future prompt tweak that breaks parsing surfaces
 * here instead of silently degrading the card.
 */
import { describe, expect, it } from 'vitest';

import {
  parseRecommendation,
  stripRecommendationSection
} from '../src/lib/research/parse-recommendation';

const _FULL_BODY = `## Recommendation

**Action**: BUY
**Target price**: $185.50
**Horizon**: 12 months
**Key risks**:
- Elevated forward P/E vs sector median
- Concentrated revenue exposure to a single customer
- Liquidity tightening in the credit window

## Growth

Some growth prose with [fact:11111111-1111-1111-1111-111111111111].

## Value

Some value prose.

## Momentum

Some momentum prose.
`;

describe('parseRecommendation', () => {
  it('returns empty fields when body is null', () => {
    const r = parseRecommendation(null);
    expect(r.action).toBeNull();
    expect(r.targetPrice).toBeNull();
    expect(r.risks).toEqual([]);
  });

  it('extracts action / target / horizon / risks from the canonical shape', () => {
    const r = parseRecommendation(_FULL_BODY);
    expect(r.action).toBe('BUY');
    expect(r.targetPrice).toBe(185.5);
    expect(r.targetPriceLabel).toBe('$185.50');
    expect(r.horizon).toBe('12 months');
    expect(r.risks).toEqual([
      'Elevated forward P/E vs sector median',
      'Concentrated revenue exposure to a single customer',
      'Liquidity tightening in the credit window'
    ]);
    expect(r.lowConfidence).toBe(false);
  });

  it('detects low-confidence rating from the action suffix', () => {
    const body = `## Recommendation

**Action**: HOLD (low-confidence pending tier-A data)
**Target price**: $174.50
**Horizon**: 12 months
**Key risks**:
- Missing eps_growth_yoy tier-A input
`;
    const r = parseRecommendation(body);
    expect(r.action).toBe('HOLD');
    expect(r.lowConfidence).toBe(true);
  });

  it('detects low-confidence from prose mentioning missing tier-A inputs', () => {
    const body = `## Recommendation

**Action**: HOLD
**Target price**: $100.00
**Horizon**: 12 months
**Key risks**:
- ...

The rating is pending the arrival of missing tier-A inputs.
`;
    const r = parseRecommendation(body);
    expect(r.lowConfidence).toBe(true);
  });

  it('extracts AVOID and BUY actions case-insensitively', () => {
    expect(parseRecommendation('## Recommendation\n\n**Action**: avoid\n').action).toBe('AVOID');
    expect(parseRecommendation('## Recommendation\n\n**Action**: Buy\n').action).toBe('BUY');
  });

  it('falls back to null target when no numeric value is present', () => {
    const r = parseRecommendation('## Recommendation\n\n**Target price**: TBD\n');
    expect(r.targetPrice).toBeNull();
    expect(r.targetPriceLabel).toBe('TBD');
  });

  it('handles targets with currency suffix instead of $ prefix', () => {
    const r = parseRecommendation('## Recommendation\n\n**Target price**: 174.50 USD\n');
    expect(r.targetPrice).toBe(174.5);
  });

  it('returns empty risks when the Key risks section is absent', () => {
    const r = parseRecommendation(
      '## Recommendation\n\n**Action**: HOLD\n**Target price**: $100\n'
    );
    expect(r.risks).toEqual([]);
  });

  it('ignores **Action**: references outside the Recommendation section', () => {
    // A pillar prose paragraph happens to use the same bold label —
    // the parser must NOT pick that up.
    const body = `## Recommendation

**Action**: HOLD

## Growth

Earnings cadence suggests **Action**: BUY in the next quarter, per analyst commentary.
`;
    expect(parseRecommendation(body).action).toBe('HOLD');
  });
});

describe('stripRecommendationSection', () => {
  it('removes the Recommendation block while keeping the rest of the body', () => {
    const stripped = stripRecommendationSection(_FULL_BODY);
    expect(stripped).not.toContain('## Recommendation');
    expect(stripped).not.toContain('Elevated forward P/E vs sector median');
    expect(stripped).toContain('## Growth');
    expect(stripped).toContain('## Value');
    expect(stripped).toContain('## Momentum');
  });

  it('returns empty string for null input', () => {
    expect(stripRecommendationSection(null)).toBe('');
  });

  it('returns the body unchanged when no Recommendation section exists', () => {
    const body = '## Growth\n\nSome prose.\n';
    expect(stripRecommendationSection(body)).toBe(body);
  });
});
