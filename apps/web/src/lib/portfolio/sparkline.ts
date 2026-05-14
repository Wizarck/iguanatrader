/**
 * Pure SVG path builder for the EquitySparkline component.
 *
 * Lives outside `.svelte` so it is unit-testable without a DOM.
 * Decimal values are converted to `Number` upstream — that conversion is
 * acceptable for PLOTTING precision only (bounded equity values rendered
 * over ~240 pixels); never for user-facing money math.
 */

/**
 * Build the `d` attribute of an SVG `<path>` over the given values.
 *
 * @param values - Numeric equity series in chronological ASC order.
 * @param width - SVG viewport width in pixels (must be > 0).
 * @param height - SVG viewport height in pixels (must be > 0).
 * @returns SVG path `d` attribute (e.g. `"M 0 36 L 120 18 L 240 0"`),
 *   empty string for `values.length === 0`,
 *   `"M 0 36 L 240 36"` (flat baseline) for `values.length === 1`.
 *   X coordinates clamped to `[0, width]`; Y to `[0, height]`.
 */
export function buildSparklinePath(values: number[], width: number, height: number): string {
  if (values.length === 0) return '';
  if (values.length === 1) {
    const midY = clamp(height / 2, 0, height);
    return `M 0 ${fmt(midY)} L ${fmt(width)} ${fmt(midY)}`;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min;
  const stepX = width / (values.length - 1);

  const points = values.map((v, i) => {
    const x = clamp(i * stepX, 0, width);
    // Flat series → middle of viewport; otherwise normalise + invert Y
    // so higher equity sits closer to the top of the SVG.
    const normalisedY = range === 0 ? height / 2 : height - ((v - min) / range) * height;
    const y = clamp(normalisedY, 0, height);
    return `${fmt(x)} ${fmt(y)}`;
  });

  return `M ${points[0]} ${points
    .slice(1)
    .map((p) => `L ${p}`)
    .join(' ')}`;
}

function clamp(value: number, min: number, max: number): number {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

function fmt(n: number): string {
  return Number.isInteger(n) ? n.toString() : n.toFixed(2);
}
