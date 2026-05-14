/**
 * Pure countdown formatter for approval cards (slice approvals-dashboard-ui).
 *
 * Inputs:
 *   - `expiresAt`: ISO 8601 datetime string (UTC) — backend ground truth.
 *   - `now`: a `Date` reference taken at render-time. The caller (Svelte
 *     component) updates it once per second via `$state` + `setInterval`,
 *     so this helper stays pure and unit-testable.
 *
 * Output buckets (delta = expiresAt - now, in seconds):
 *   - delta <= 0          → "Expirado"
 *   - delta < 60          → "Ns"
 *   - 60 <= delta < 3600  → "Mm Ss"
 *   - delta >= 3600       → "Hh Mm"
 *
 * Spanish copy intentional — page copy is Spanish per project norms.
 */
export function formatCountdown(expiresAt: string, now: Date): string {
  const expiresMs = Date.parse(expiresAt);
  if (Number.isNaN(expiresMs)) return 'Expirado';

  const deltaMs = expiresMs - now.getTime();
  const deltaSec = Math.floor(deltaMs / 1000);

  if (deltaSec <= 0) return 'Expirado';
  if (deltaSec < 60) return `${deltaSec}s`;
  if (deltaSec < 3600) {
    const minutes = Math.floor(deltaSec / 60);
    const seconds = deltaSec % 60;
    return `${minutes}m ${seconds}s`;
  }
  const hours = Math.floor(deltaSec / 3600);
  const minutes = Math.floor((deltaSec % 3600) / 60);
  return `${hours}h ${minutes}m`;
}
