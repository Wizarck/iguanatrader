/**
 * Pure tests for `buildSparklinePath` (slice portfolio-dashboard-mvp).
 *
 * Covers: 0 / 1 / 2 / N points, flat series, ascending series,
 * descending series, X/Y clamping.
 */

import { describe, expect, it } from 'vitest';

import { buildSparklinePath } from '../src/lib/portfolio/sparkline';

const W = 240;
const H = 72;

describe('buildSparklinePath', () => {
  it('returns empty string for 0 points', () => {
    expect(buildSparklinePath([], W, H)).toBe('');
  });

  it('renders a horizontal baseline for 1 point', () => {
    const d = buildSparklinePath([100], W, H);
    expect(d).toBe('M 0 36 L 240 36');
  });

  it('renders a line between exactly 2 points', () => {
    const d = buildSparklinePath([100, 200], W, H);
    expect(d.startsWith('M ')).toBe(true);
    expect(d).toContain('L ');
    // Y axis is inverted: higher equity (200) ends near the top (y=0)
    // and the starting equity (100) sits at the bottom (y=72).
    expect(d).toContain('M 0 72');
    expect(d).toContain('L 240 0');
  });

  it('renders an N-point path with N-1 line segments', () => {
    const d = buildSparklinePath([1, 2, 3, 4, 5], W, H);
    const lineCount = (d.match(/L /g) ?? []).length;
    expect(lineCount).toBe(4);
  });

  it('flat series renders all points at vertical midpoint', () => {
    const d = buildSparklinePath([50, 50, 50], W, H);
    // All Y values are 36 (height / 2).
    const ys = d.match(/\d+(\.\d+)? 36/g) ?? [];
    expect(ys.length).toBeGreaterThanOrEqual(3);
  });

  it('descending series ends near the bottom', () => {
    const d = buildSparklinePath([200, 150, 100], W, H);
    expect(d).toContain('M 0 0');
    expect(d.endsWith('L 240 72')).toBe(true);
  });

  it('clamps X coordinates to [0, width]', () => {
    const d = buildSparklinePath([1, 2, 3, 4, 5], W, H);
    // Match all X values (first number on each pair).
    const matches = [...d.matchAll(/[ML] (\d+(?:\.\d+)?) /g)];
    for (const m of matches) {
      const x = Number(m[1]);
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(W);
    }
  });

  it('clamps Y coordinates to [0, height]', () => {
    const d = buildSparklinePath([10, 20, 30, 40], W, H);
    const matches = [...d.matchAll(/ (\d+(?:\.\d+)?)$/gm)];
    // Pull all coordinate pairs via a different regex; check Y bounds.
    const allCoords = [...d.matchAll(/(\d+(?:\.\d+)?) (\d+(?:\.\d+)?)/g)];
    for (const c of allCoords) {
      const y = Number(c[2]);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(H);
    }
    expect(matches.length).toBeGreaterThan(0);
  });
});
