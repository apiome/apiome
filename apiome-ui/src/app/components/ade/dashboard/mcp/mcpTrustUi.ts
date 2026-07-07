/**
 * Composite trust profile — shared types & pure presentation helpers
 * (V2-MCP-31.4 / MCAT-17.4, #4644).
 *
 * The Insight tab's capstone "Composite trust radar" synthesizes the many scattered
 * reliability/safety signals into a single five-axis glance: **quality** (grade), **safety**
 * (annotation coverage + destructive/auth posture), **documentation** (coverage), **stability**
 * (inverse breaking-change rate), and **responsiveness** (latency/error). The five 0–100 axes are
 * computed server-side (apiome-rest `insight/trust`); this module is the *pure, React-free* client
 * layer over that payload: the typed wire shape, a defensive parser, and the projections the
 * {@link TrustProfilePanel} renders (the {@link Radar}-ready axis list, the score-band tones, and
 * the value formatters).
 *
 * It is deliberately a **heuristic** composite — a synthesized glance, not an official rating — and
 * the panel labels it as such. The one hard rule the parser preserves: an axis whose input is
 * missing is an explicit *gap* (`value: null`, `available: false`), never a zero, so a never-tested
 * server reads as "not measured", not "scored zero". Keeping this free of React/JSX lets it be
 * unit-tested directly and keeps the panel free of payload-shaping branches — mirroring
 * {@link mcpReliabilityHealthFromPayload}.
 */

import type { ChartSeriesTone, RadarAxis } from '@/app/components/ui/mcp/charts';

// --- Wire types ------------------------------------------------------------------------------
// One-to-one with the apiome-rest `McpTrustProfileOut` / `McpTrustAxisOut` models.

/** One normalized 0–100 axis of the trust profile (or an explicit gap when its input is missing). */
export interface McpTrustAxis {
  /** Stable key: `quality` / `safety` / `documentation` / `stability` / `responsiveness`. */
  key: string;
  /** Human axis label (e.g. "Quality"). */
  label: string;
  /** The 0–100 score, or `null` when the axis is a gap (its input was missing). */
  value: number | null;
  /** True when the axis could be computed; false marks a gap the radar renders as unmeasured. */
  available: boolean;
  /** Always-shown one-line basis for the score (e.g. "Grade B · 84/100", "Never tested"). */
  detail: string;
  /** The "how this is computed" text the panel reveals on hover (the ticket's methodology-on-hover). */
  methodology: string;
}

/** The full five-axis composite profile plus the mean of the available axes. */
export interface McpTrustProfile {
  /** The five axes in canonical (clockwise) radar order; some may be gaps. */
  axes: McpTrustAxis[];
  /** The mean of the *available* axis values (gaps excluded), or `null` when none are available. */
  overall: number | null;
  /** How many axes could be computed. */
  availableCount: number;
  /** Total axes (five). */
  axisCount: number;
  /** The snapshot the surface-derived axes were read from, or `null` when never discovered. */
  versionId: string | null;
  /** The endpoint's configured auth scheme the safety axis cross-references, or `null`. */
  authType: string | null;
}

// --- Defensive coercion ----------------------------------------------------------------------

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asScore(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asInt(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : 0;
}

/** Parse one axis defensively, or `null` when it carries no resolvable key. */
function axisFromPayload(raw: unknown): McpTrustAxis | null {
  const r = (raw ?? {}) as Record<string, unknown>;
  const key = asString(r.key);
  if (!key) return null;
  const value = asScore(r.value);
  // Re-derive availability from the value so a gap can never render as a numeric score, and vice
  // versa: an axis is available exactly when the wire says so *and* it carries a finite value.
  const available = r.available === true && value !== null;
  return {
    key,
    label: asString(r.label) ?? key,
    value: available ? value : null,
    available,
    detail: asString(r.detail) ?? '',
    methodology: asString(r.methodology) ?? '',
  };
}

/**
 * Parse an `insight/trust` response into a {@link McpTrustProfile}, or `null` when the payload is
 * absent/malformed (the panel then shows its empty state, never a crash). The `overall` composite
 * and `availableCount` are re-derived from the parsed axes so the headline can never disagree with
 * the axes the radar draws.
 */
export function mcpTrustProfileFromPayload(data: unknown): McpTrustProfile | null {
  const payload = (data ?? {}) as Record<string, unknown>;
  const raw = payload.profile;
  if (!raw || typeof raw !== 'object') return null;
  const p = raw as Record<string, unknown>;

  const axes = (Array.isArray(p.axes) ? p.axes : [])
    .map(axisFromPayload)
    .filter((axis): axis is McpTrustAxis => axis !== null);

  // Re-derive the composite from the available axes so it always matches what is drawn.
  const available = axes.filter((axis) => axis.available && axis.value !== null);
  const overall =
    available.length > 0
      ? Math.round((available.reduce((sum, axis) => sum + (axis.value ?? 0), 0) / available.length) * 10) / 10
      : null;

  return {
    axes,
    overall,
    availableCount: available.length,
    axisCount: axes.length || asInt(p.axis_count),
    versionId: asString(payload.version_id),
    authType: asString(payload.auth_type),
  };
}

// --- Score bands -----------------------------------------------------------------------------

/** The band a 0–100 axis (or the overall composite) falls into — drives its display tone. */
export type McpTrustBand = 'strong' | 'fair' | 'weak' | 'gap';

/**
 * Classify an axis/overall value into its display band: `strong` (≥80), `fair` (≥50), `weak`
 * (<50), or `gap` (`null` — not measured). Kept distinct from `weak` so an unmeasured axis is never
 * coloured like a poorly-scoring one.
 */
export function mcpTrustBand(value: number | null): McpTrustBand {
  if (value === null) return 'gap';
  if (value >= 80) return 'strong';
  if (value >= 50) return 'fair';
  return 'weak';
}

/** The chart-series tone each band paints with (for the radar fill + swatches). */
export const MCP_TRUST_BAND_TONE: Record<McpTrustBand, ChartSeriesTone> = {
  strong: 'green',
  fair: 'amber',
  weak: 'red',
  gap: 'neutral',
};

/** Format a nullable 0–100 axis value for display: a whole number, or `—` for a gap. */
export function mcpTrustFormatValue(value: number | null): string {
  if (value === null) return '—';
  return `${Math.round(value)}`;
}

// --- Radar projection ------------------------------------------------------------------------

/**
 * Project the profile's axes onto the {@link Radar} primitive's axis list. A gap (unmeasured axis)
 * has no polygon value, so it is drawn at the centre (`0`); the panel's axis list — not the polygon
 * — is the source of truth for which axes are gaps, and it labels them explicitly. The order is the
 * server's canonical clockwise order (quality → safety → documentation → stability → responsiveness).
 */
export function mcpTrustRadarAxes(profile: McpTrustProfile): RadarAxis[] {
  return profile.axes.map((axis) => ({ label: axis.label, value: axis.value ?? 0 }));
}

/** The fixed radar domain — every axis is already normalized to a 0–100 scale. */
export const MCP_TRUST_AXIS_MAX = 100;
