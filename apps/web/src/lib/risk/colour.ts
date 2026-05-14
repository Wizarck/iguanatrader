/**
 * Pure colour-tier mapper for risk utilisation bars (slice
 * risk-dashboard-ui).
 *
 * Same hoist pattern as α's `variants.ts` + portfolio's
 * `sparkline.ts` / `format.ts`: a pure function that maps the
 * utilisation ratio (utilisation / cap, clamped) to a Badge-style
 * variant token. Lives in a separate module so it's unit-testable
 * without a DOM and reusable across `RiskUtilisationCard` + future
 * `/approvals` per-evaluation bars.
 *
 * Tiers (per proposal §What):
 *   - `< 0.5`        → `success`     (--success OKLCH green)
 *   - `0.5 .. 0.8`   → `accent`      (--accent  OKLCH cyan)
 *   - `> 0.8`        → `destructive` (--destructive OKLCH red)
 *
 * Boundary semantics (closed-left): `0.5` itself is `accent`;
 * `0.8` itself is `accent`; anything strictly above `0.8` is
 * `destructive`. NaN / Infinity coerce to `destructive` (defensive:
 * the only way to hit that path is a corrupted backend payload, and
 * showing red is the safer failure).
 */

export type UtilisationTier = 'success' | 'accent' | 'destructive';

export function utilisationBarColour(ratio: number): UtilisationTier {
  if (!Number.isFinite(ratio)) return 'destructive';
  if (ratio < 0.5) return 'success';
  if (ratio <= 0.8) return 'accent';
  return 'destructive';
}
