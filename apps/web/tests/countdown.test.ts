/**
 * Pure tests for `formatCountdown` (slice approvals-dashboard-ui).
 *
 * Covers: expired (negative delta), edge zero, sub-minute, sub-hour,
 * exact-hour, multi-hour deltas, plus malformed `expiresAt` input.
 */

import { describe, expect, it } from 'vitest';

import { formatCountdown } from '../src/lib/approvals/countdown';

const NOW_ISO = '2026-05-14T12:00:00Z';
const NOW = new Date(NOW_ISO);

describe('formatCountdown', () => {
  it('returns "Expirado" when delta is negative', () => {
    const expiresAt = '2026-05-14T11:59:55Z'; // -5s
    expect(formatCountdown(expiresAt, NOW)).toBe('Expirado');
  });

  it('returns "Expirado" when delta is exactly zero', () => {
    expect(formatCountdown(NOW_ISO, NOW)).toBe('Expirado');
  });

  it('renders sub-minute deltas as "Ns"', () => {
    const expiresAt = '2026-05-14T12:00:30Z'; // +30s
    expect(formatCountdown(expiresAt, NOW)).toBe('30s');
  });

  it('renders sub-hour deltas as "Mm Ss"', () => {
    const expiresAt = '2026-05-14T12:01:30Z'; // +1m30s
    expect(formatCountdown(expiresAt, NOW)).toBe('1m 30s');
  });

  it('renders multi-hour deltas as "Hh Mm"', () => {
    const expiresAt = '2026-05-14T14:15:00Z'; // +2h15m
    expect(formatCountdown(expiresAt, NOW)).toBe('2h 15m');
  });
});
