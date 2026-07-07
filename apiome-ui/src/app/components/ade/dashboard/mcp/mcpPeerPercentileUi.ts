/**
 * Peer percentile & category ranking — shared types & pure presentation helpers
 * (V2-MCP-32.3 / MCAT-18.3, #4647).
 *
 * "Is this a good weather server?" needs a *peer baseline*, not an absolute grade. The backend ranks
 * an endpoint against the other live servers in its catalog **category** on four axes — grade, safety,
 * documentation, and latency — and this module is the *pure, React-free* client layer over that
 * `insight/percentile` payload: the typed wire shape, a defensive parser, and the projections the
 * {@link PeerPercentilePanel} renders ("top 10% for documentation"-style badges).
 *
 * The one hard rule the parser preserves: an axis the server does not have measured (never scored, no
 * tools, never tested) is an explicit *gap* (`available: false`, `value: null`), never a zero, so an
 * undiscovered server reads as "not ranked", not "ranked last". Keeping this free of React/JSX lets it
 * be unit-tested directly and keeps the panel free of payload-shaping branches — mirroring
 * {@link mcpTrustProfileFromPayload}.
 */

import type { McpBadgeTone } from './mcpUiPrimitives';

// --- Wire types ------------------------------------------------------------------------------
// One-to-one with the apiome-rest `McpPeerAxisPercentileOut` / `McpPeerPercentileOut` models.

/** One axis of a server's peer ranking within its category (or a gap when unmeasured). */
export interface McpPeerAxis {
  /** Stable key: `grade` / `safety` / `documentation` / `latency`. */
  key: string;
  /** Human axis label (e.g. "Documentation"). */
  label: string;
  /** The server's own 0–100 axis value, or `null` when the axis is a gap. */
  value: number | null;
  /** Share of the category cohort at or below this server (higher = better), or `null` for a gap. */
  percentile: number | null;
  /** Ordinal position within the cohort (`1` = best), or `null` for a gap. */
  rank: number | null;
  /** The "top N%" the badge renders (`ceil(100 * rank / cohort_size)`), or `null` for a gap. */
  topPercent: number | null;
  /** How many peers in the category have this axis measured. */
  cohortSize: number;
  /** True when the axis could be ranked; false marks a gap. */
  available: boolean;
  /** Always-shown one-line basis (e.g. "Rank 2 of 8 · top 25%", "Not measured"). */
  detail: string;
}

/** The full peer-ranking profile for one endpoint within its catalog category. */
export interface McpPeerPercentileProfile {
  /** The cohort's category, or `null` for the uncategorized cohort. */
  category: string | null;
  /** Total live endpoints in the category, including this one. */
  cohortSize: number;
  /** The four axis rankings in canonical order (grade → safety → documentation → latency). */
  axes: McpPeerAxis[];
  /** How many axes could be ranked (not gaps). */
  rankedCount: number;
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
function axisFromPayload(raw: unknown): McpPeerAxis | null {
  const r = (raw ?? {}) as Record<string, unknown>;
  const key = asString(r.key);
  if (!key) return null;
  const percentile = asScore(r.percentile);
  // Re-derive availability from the value so a gap can never render as a ranked axis and vice versa:
  // an axis is available exactly when the wire says so *and* it carries a finite value + percentile.
  const value = asScore(r.value);
  const available = r.available === true && value !== null && percentile !== null;
  return {
    key,
    label: asString(r.label) ?? key,
    value: available ? value : null,
    percentile: available ? percentile : null,
    rank: available ? asInt(r.rank) : null,
    topPercent: available ? asInt(r.top_percent) : null,
    cohortSize: asInt(r.cohort_size),
    available,
    detail: asString(r.detail) ?? '',
  };
}

/**
 * Parse an `insight/percentile` response into a {@link McpPeerPercentileProfile}, or `null` when the
 * payload is absent/malformed (the panel then shows its empty state, never a crash). `rankedCount` is
 * re-derived from the parsed axes so the panel's "N of 4 axes ranked" caption always matches.
 */
export function mcpPeerPercentileFromPayload(data: unknown): McpPeerPercentileProfile | null {
  const payload = (data ?? {}) as Record<string, unknown>;
  const raw = payload.profile;
  if (!raw || typeof raw !== 'object') return null;
  const p = raw as Record<string, unknown>;

  const axes = (Array.isArray(p.axes) ? p.axes : [])
    .map(axisFromPayload)
    .filter((axis): axis is McpPeerAxis => axis !== null);

  return {
    category: asString(p.category),
    cohortSize: asInt(p.cohort_size),
    axes,
    rankedCount: axes.filter((axis) => axis.available).length,
  };
}

// --- Standing bands --------------------------------------------------------------------------

/** The relative-standing band a ranked axis falls into — drives its badge tone + phrasing. */
export type McpPeerBand = 'leading' | 'strong' | 'middle' | 'trailing' | 'gap';

/**
 * Classify a ranked axis's "top N%" into a standing band: `leading` (top 10%), `strong` (top 25%),
 * `middle` (top 50%), `trailing` (bottom half), or `gap` (unmeasured). A gap is kept distinct so an
 * unranked axis is never coloured like a poorly-ranked one.
 */
export function mcpPeerBand(axis: McpPeerAxis): McpPeerBand {
  if (!axis.available || axis.topPercent === null) return 'gap';
  if (axis.topPercent <= 10) return 'leading';
  if (axis.topPercent <= 25) return 'strong';
  if (axis.topPercent <= 50) return 'middle';
  return 'trailing';
}

/** The badge tone each standing band paints with (mirrors the shared {@link McpBadgeTone} palette). */
export const MCP_PEER_BAND_TONE: Record<McpPeerBand, McpBadgeTone> = {
  leading: 'green',
  strong: 'blue',
  middle: 'indigo',
  trailing: 'slate',
  gap: 'slate',
};

/**
 * The short badge label for a ranked axis, e.g. "Top 10%", or "Only in category" for a lone member.
 * A gap yields `null` (the panel renders it as "Not ranked" rather than a badge). A single-member
 * cohort is called out explicitly rather than shown as a meaningless "top 100%".
 */
export function mcpPeerBadgeLabel(axis: McpPeerAxis): string | null {
  if (!axis.available || axis.topPercent === null) return null;
  if (axis.cohortSize <= 1) return 'Only in category';
  return `Top ${axis.topPercent}%`;
}

/**
 * A friendly display name for the cohort's category — the raw category, or "uncategorized servers"
 * for the `null` cohort — so the panel can say "ranked against 7 finance servers".
 */
export function mcpPeerCategoryLabel(category: string | null): string {
  return category && category.trim().length > 0 ? category : 'uncategorized servers';
}
