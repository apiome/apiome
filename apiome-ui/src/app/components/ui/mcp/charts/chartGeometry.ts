/**
 * Token-driven SVG chart kit — pure geometry helpers (V2-MCP-28.3 / MCAT-14.3).
 *
 * All the coordinate math the chart primitives need, kept React-free so it can be unit-tested in
 * isolation and so the components stay declarative. Everything here is deterministic and SSR-safe
 * (no `Math.random`, no DOM). Angles are measured clockwise from 12 o'clock (top), matching how the
 * donut/gauge arcs read visually.
 */

/** A 2-D point in SVG user units. */
export interface Point {
  x: number;
  y: number;
}

/** Clamp `value` into the inclusive `[min, max]` range. */
export function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

/**
 * The largest finite value in `values`, or `0` for an empty/all-non-finite list. Used to scale bars
 * and sparklines to their own maximum when the consumer does not pin a domain.
 */
export function maxValue(values: readonly number[]): number {
  let max = 0;
  for (const v of values) {
    if (Number.isFinite(v) && v > max) max = v;
  }
  return max;
}

/** Sum of the finite, non-negative values in `values` (negatives and NaN are treated as `0`). */
export function sumValues(values: readonly number[]): number {
  let total = 0;
  for (const v of values) {
    if (Number.isFinite(v) && v > 0) total += v;
  }
  return total;
}

/**
 * Map a series of `values` to evenly-spaced points inside a `width`×`height` box with `padding` on
 * every side, scaling the y-axis to `[0, domainMax]` (higher values sit higher, i.e. smaller `y`).
 * A single value renders as a flat mid-line. Returns an empty array for an empty series.
 */
export function sparklinePoints(
  values: readonly number[],
  width: number,
  height: number,
  padding: number,
  domainMax?: number,
): Point[] {
  if (values.length === 0) return [];
  const innerW = Math.max(1, width - padding * 2);
  const innerH = Math.max(1, height - padding * 2);
  const max = domainMax && domainMax > 0 ? domainMax : maxValue(values) || 1;
  const stepX = values.length === 1 ? 0 : innerW / (values.length - 1);
  return values.map((raw, i) => {
    const v = Number.isFinite(raw) ? clamp(raw, 0, max) : 0;
    const x = values.length === 1 ? padding + innerW / 2 : padding + stepX * i;
    const y = padding + innerH * (1 - v / max);
    return { x, y };
  });
}

/** Turn a list of points into an SVG polyline/path `d` string (`M`/`L`), rounded to 2 decimals. */
export function pointsToPath(points: readonly Point[]): string {
  return points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(' ');
}

/** Point on the circle of radius `r` about (`cx`,`cy`) at `angleDeg` clockwise from the top. */
export function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number): Point {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

/**
 * SVG `d` for a **donut/ring arc** — an annular wedge between `innerR` and `outerR` sweeping from
 * `startAngle` to `endAngle` (degrees, clockwise from top). A full 360° sweep is emitted as two
 * half-arcs so the path is not degenerate. Returns `''` for a non-positive sweep.
 */
export function describeAnnularArc(
  cx: number,
  cy: number,
  innerR: number,
  outerR: number,
  startAngle: number,
  endAngle: number,
): string {
  const sweep = endAngle - startAngle;
  if (sweep <= 0) return '';
  if (sweep >= 360) {
    // Full ring: split into two 180° annular wedges to avoid a zero-length arc.
    const mid = startAngle + 180;
    return (
      describeAnnularArc(cx, cy, innerR, outerR, startAngle, mid) +
      ' ' +
      describeAnnularArc(cx, cy, innerR, outerR, mid, startAngle + 360)
    );
  }
  const largeArc = sweep > 180 ? 1 : 0;
  const oStart = polarToCartesian(cx, cy, outerR, startAngle);
  const oEnd = polarToCartesian(cx, cy, outerR, endAngle);
  const iEnd = polarToCartesian(cx, cy, innerR, endAngle);
  const iStart = polarToCartesian(cx, cy, innerR, startAngle);
  return [
    `M ${oStart.x.toFixed(2)} ${oStart.y.toFixed(2)}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 1 ${oEnd.x.toFixed(2)} ${oEnd.y.toFixed(2)}`,
    `L ${iEnd.x.toFixed(2)} ${iEnd.y.toFixed(2)}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 0 ${iStart.x.toFixed(2)} ${iStart.y.toFixed(2)}`,
    'Z',
  ].join(' ');
}

/**
 * SVG `d` for an **open stroked arc** (no fill) of radius `r` from `startAngle` to `endAngle`,
 * used by the gauge track/value. Returns `''` for a non-positive sweep.
 */
export function describeArc(
  cx: number,
  cy: number,
  r: number,
  startAngle: number,
  endAngle: number,
): string {
  const sweep = endAngle - startAngle;
  if (sweep <= 0) return '';
  const capped = Math.min(sweep, 359.999);
  const start = polarToCartesian(cx, cy, r, startAngle);
  const end = polarToCartesian(cx, cy, r, startAngle + capped);
  const largeArc = capped > 180 ? 1 : 0;
  return [
    `M ${start.x.toFixed(2)} ${start.y.toFixed(2)}`,
    `A ${r} ${r} 0 ${largeArc} 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`,
  ].join(' ');
}

/**
 * The vertices of a radar polygon: for each of `values`, a point at the fraction `value/max` of the
 * radius `r` about (`cx`,`cy`), with the first axis pointing straight up and the rest spaced evenly
 * clockwise. Values are clamped to `[0, max]`. Returns an empty array for an empty series.
 */
export function radarPoints(
  values: readonly number[],
  max: number,
  cx: number,
  cy: number,
  r: number,
): Point[] {
  if (values.length === 0) return [];
  const safeMax = max > 0 ? max : 1;
  const step = 360 / values.length;
  return values.map((raw, i) => {
    const frac = clamp(Number.isFinite(raw) ? raw : 0, 0, safeMax) / safeMax;
    return polarToCartesian(cx, cy, r * frac, step * i);
  });
}

/** Turn radar/polygon points into a closed SVG polygon `points` attribute string. */
export function polygonPoints(points: readonly Point[]): string {
  return points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
}

/**
 * Normalize a value into a `[0, 1]` intensity for the heatmap, relative to `max` (defaults to 1).
 * Non-finite or non-positive values map to `0`. Used to drive per-cell fill opacity.
 */
export function intensity(value: number, max: number): number {
  const m = max > 0 ? max : 1;
  return clamp(Number.isFinite(value) ? value : 0, 0, m) / m;
}
