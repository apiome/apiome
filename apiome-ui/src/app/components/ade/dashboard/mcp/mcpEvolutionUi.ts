/**
 * MCP surface-evolution series — shared types & pure presentation helpers
 * (V2-MCP-30.1 / MCAT-16.1, #4636).
 *
 * The Insight tab's "Capability churn timeline" plots, per discovery snapshot, how much the server's
 * surface changed — the added / removed / modified counts recorded in `mcp_version_changes` — as a
 * stacked column over an oldest→newest axis, served by apiome-rest through the Next.js proxy at
 * `/api/mcp/endpoints/{id}/insight/evolution`. This module is the *pure, React-free* client layer
 * over that payload: the typed wire shape, a defensive parser, and the projection that turns the
 * series into what the {@link StackedTimeline} primitive renders (plus the per-column version ids the
 * panel deep-links to the diff viewer with). Keeping it free of React/JSX lets it be unit-tested
 * directly and keeps the panel component free of payload-shaping branches — mirroring
 * {@link mcpInsightSurfaceFromPayload} and {@link mcpCapabilityGraphUi}.
 */

import type {
  ChartSeriesTone,
  StackPeriod,
  StackSeries,
} from '@/app/components/ui/mcp/charts';
import { mcpVersionSeqLabel } from './mcpVersionsUi';

// --- Wire types ------------------------------------------------------------------------------
// One-to-one with the apiome-rest `McpEvolutionPoint` / `McpInsightEvolutionResponse` envelope.

/** Per-kind capability tally for one snapshot (mirrors `McpTypeCountsOut`). */
export interface McpEvolutionTypeCounts {
  tools: number;
  resources: number;
  resource_templates: number;
  prompts: number;
  /** Always the sum of the four kinds. */
  total: number;
}

/** Per-direction churn tally a snapshot introduced relative to the prior version. */
export interface McpEvolutionChangeCounts {
  added: number;
  removed: number;
  modified: number;
  /** Always `added + removed + modified`. */
  total: number;
}

/** One point of an endpoint's per-version evolution series. */
export interface McpEvolutionPoint {
  version_id: string;
  version_seq: number;
  version_tag: string | null;
  /** When the snapshot was discovered (ISO 8601), the axis is ordered by. */
  discovered_at: string | null;
  /** True when the endpoint's `current_version_id` points at this snapshot. */
  is_current: boolean;
  type_counts: McpEvolutionTypeCounts;
  score: number | null;
  grade: string | null;
  change_counts: McpEvolutionChangeCounts;
}

// --- Defensive coercion ----------------------------------------------------------------------

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asInt(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : 0;
}

function asScore(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : null;
}

/** Parse a `{ tools, resources, resource_templates, prompts, total }` block, deriving `total`. */
function typeCountsFromPayload(raw: unknown): McpEvolutionTypeCounts {
  const r = (raw ?? {}) as Record<string, unknown>;
  const tools = asInt(r.tools);
  const resources = asInt(r.resources);
  const resource_templates = asInt(r.resource_templates);
  const prompts = asInt(r.prompts);
  return {
    tools,
    resources,
    resource_templates,
    prompts,
    // Derive from the parts so the total can never disagree with the kinds it sums.
    total: tools + resources + resource_templates + prompts,
  };
}

/** Parse a `{ added, removed, modified, total }` churn block, deriving `total` from the parts. */
function changeCountsFromPayload(raw: unknown): McpEvolutionChangeCounts {
  const r = (raw ?? {}) as Record<string, unknown>;
  const added = asInt(r.added);
  const removed = asInt(r.removed);
  const modified = asInt(r.modified);
  return { added, removed, modified, total: added + removed + modified };
}

/** Parse one evolution point defensively, or `null` when it carries no resolvable version id. */
function pointFromPayload(raw: unknown): McpEvolutionPoint | null {
  const r = (raw ?? {}) as Record<string, unknown>;
  const versionId = asString(r.version_id);
  if (!versionId) return null;
  return {
    version_id: versionId,
    version_seq: asInt(r.version_seq),
    version_tag: asString(r.version_tag),
    discovered_at: asString(r.discovered_at),
    is_current: r.is_current === true,
    type_counts: typeCountsFromPayload(r.type_counts),
    score: asScore(r.score),
    grade: asString(r.grade),
    change_counts: changeCountsFromPayload(r.change_counts),
  };
}

/**
 * Parse an `insight/evolution` response into an oldest-first {@link McpEvolutionPoint} list. The REST
 * API already orders oldest-first, but we re-sort by `version_seq` ascending defensively so the
 * timeline's axis is stable regardless of payload order. Malformed points (no version id) are dropped
 * so a partial payload still renders a coherent series rather than throwing. A missing/empty `series`
 * yields `[]` — the panel shows its empty state, never a crash.
 */
export function mcpEvolutionSeriesFromPayload(data: unknown): McpEvolutionPoint[] {
  const payload = (data ?? {}) as Record<string, unknown>;
  const series = Array.isArray(payload.series) ? payload.series : [];
  return series
    .map(pointFromPayload)
    .filter((p): p is McpEvolutionPoint => p !== null)
    .sort((a, b) => a.version_seq - b.version_seq);
}

// --- Churn-timeline projection ---------------------------------------------------------------

/** The three churn bands, bottom→top, each pinned to the diff viewer's own colour language. */
export const MCP_CHURN_SERIES: readonly StackSeries[] = [
  { key: 'added', label: 'Added', tone: 'green' satisfies ChartSeriesTone },
  { key: 'removed', label: 'Removed', tone: 'red' satisfies ChartSeriesTone },
  { key: 'modified', label: 'Modified', tone: 'blue' satisfies ChartSeriesTone },
];

/** The churn series projected for the {@link StackedTimeline}, plus the metadata the panel needs. */
export interface McpChurnTimeline {
  /** The stacked bands (added / removed / modified), in draw order. */
  series: readonly StackSeries[];
  /** One column per snapshot, oldest→newest, each column's churn split by direction. */
  periods: StackPeriod[];
  /** Parallel to `periods`: the `version_id` each column deep-links to. */
  versionIds: string[];
  /** Index of the current snapshot's column, or `-1` when none is current. */
  currentIndex: number;
  /** Index of the busiest (highest total churn) column, or `-1` when every column is churn-free. */
  busiestIndex: number;
  /** Total churn across the whole series (sum of every column's total). */
  totalChurn: number;
}

/**
 * A version's timeline label — the sequence label (`v3`) it reads by on the axis. The date it is
 * ordered by lives in the column's tooltip (see {@link mcpEvolutionPointDateLabel}) so the compact
 * axis stays legible even for a long history.
 */
export function mcpEvolutionPointAxisLabel(point: McpEvolutionPoint): string {
  return mcpVersionSeqLabel(point.version_seq);
}

/**
 * A human date/time tag for a snapshot: its server-supplied `version_tag` when present, else the
 * formatted `discovered_at` timestamp, else the bare sequence label — mirroring
 * {@link mcpVersionDateTag} so the churn panel and the version history read the same.
 */
export function mcpEvolutionPointDateLabel(point: McpEvolutionPoint): string {
  if (point.version_tag) return point.version_tag;
  if (point.discovered_at) {
    const ms = Date.parse(point.discovered_at);
    if (!Number.isNaN(ms)) return new Date(ms).toLocaleString();
  }
  return mcpVersionSeqLabel(point.version_seq);
}

/**
 * Project an evolution series onto the churn-timeline shape. Every snapshot becomes one column — a
 * zero-churn version still gets its slot on the axis (an empty column), so the timeline never
 * silently drops a quiet release. The busiest column (max total churn) is surfaced so the panel can
 * highlight high-churn releases; ties resolve to the earliest such version. `currentIndex` marks the
 * live snapshot's column for a subtle highlight.
 *
 * @param series The parsed evolution points, oldest-first (as {@link mcpEvolutionSeriesFromPayload}
 *   returns).
 */
export function mcpChurnTimeline(series: readonly McpEvolutionPoint[]): McpChurnTimeline {
  const periods: StackPeriod[] = [];
  const versionIds: string[] = [];
  let currentIndex = -1;
  let busiestIndex = -1;
  let busiestTotal = 0;
  let totalChurn = 0;

  series.forEach((point, index) => {
    const { added, removed, modified, total } = point.change_counts;
    periods.push({
      label: mcpEvolutionPointAxisLabel(point),
      values: { added, removed, modified },
    });
    versionIds.push(point.version_id);
    if (point.is_current && currentIndex === -1) currentIndex = index;
    totalChurn += total;
    if (total > busiestTotal) {
      busiestTotal = total;
      busiestIndex = index;
    }
  });

  return {
    series: MCP_CHURN_SERIES,
    periods,
    versionIds,
    currentIndex,
    // Only report a "busiest" release when there is real churn to highlight.
    busiestIndex: busiestTotal > 0 ? busiestIndex : -1,
    totalChurn,
  };
}

/** The tooltip / accessible label for one churn column: its version, date, and per-direction split. */
export function mcpChurnColumnLabel(point: McpEvolutionPoint): string {
  const { added, removed, modified, total } = point.change_counts;
  const noun = total === 1 ? 'change' : 'changes';
  return (
    `${mcpVersionSeqLabel(point.version_seq)} · ${mcpEvolutionPointDateLabel(point)} — ` +
    `+${added} −${removed} ~${modified} (${total} ${noun}). Click to view the diff.`
  );
}
