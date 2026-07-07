/**
 * MCP endpoint "Insight" presentation helpers (V2-MCP-28.4 / MCAT-14.4, #4630).
 *
 * The Insight tab is the home for the server-profile / evolution / reliability visualizations that
 * Epics 15–17 fill. This module holds the *pure*, React-free layer that tab relies on: the typed
 * shape of the capability-surface insight the 14.2 REST API returns
 * (`GET …/endpoints/{id}/insight/surface`), a defensive parser for it, and the small derived
 * projections (per-kind count tiles, coverage percentages) the scaffold renders as its baseline so
 * the panels have real data to prove the lazy fetch + version-selector re-fetch work.
 *
 * Keeping this free of React/JSX lets it be unit-tested directly and keeps the component free of
 * payload-shaping and number-formatting branches. Colors/spacing never appear here — consumers pass
 * domain values and receive plain data.
 */

import type { McpEndpointDetail } from './mcpBrowseUi';
import type { McpVersionSummary } from './mcpVersionsUi';

// --- Defensive scalar coercion ---------------------------------------------------------------
// Each MCP UI module carries its own tiny coercers (mirrors mcpVersionsUi) so a malformed field
// degrades to a safe default rather than throwing while a panel renders.

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asInt(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : 0;
}

function asFloat(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function asBool(value: unknown): boolean {
  return value === true;
}

// --- Surface metric types --------------------------------------------------------------------
// One-to-one with the apiome-rest `McpSurfaceMetricsOut` envelope (see apiome-rest models.py). The
// Insight scaffold only reads the roll-up numbers; the 15.x panels consume the richer per-tool
// `tool_complexity` list this preserves verbatim.

/** Per-kind capability item counts of a surface (tools/resources/templates/prompts + total). */
export interface McpTypeCounts {
  tools: number;
  resources: number;
  resource_templates: number;
  prompts: number;
  total: number;
}

/** One tool's `input_schema` complexity profile (kept whole for the 15.3 schema-shape cards). */
export interface McpToolComplexity {
  name: string;
  property_count: number;
  required_count: number;
  optional_count: number;
  documented_property_count: number;
  max_nesting_depth: number;
  uses_enum: boolean;
  uses_one_of: boolean;
  has_output_schema: boolean;
}

/** Per-hint behavioural-annotation coverage over a surface's tools (feeds the 15.4 safety panel). */
export interface McpAnnotationCoverage {
  tool_count: number;
  annotated_tools: number;
  read_only_hint: number;
  destructive_hint: number;
  idempotent_hint: number;
  open_world_hint: number;
}

/** Item- and parameter-level documentation coverage (counts + 0-100 percentages). */
export interface McpDocumentationCoverage {
  item_count: number;
  described_items: number;
  titled_items: number;
  description_pct: number;
  title_pct: number;
  tool_param_count: number;
  documented_tool_params: number;
  tool_param_description_pct: number;
}

/** The full capability-surface metrics roll-up for one version snapshot. */
export interface McpSurfaceMetrics {
  type_counts: McpTypeCounts;
  tool_complexity: McpToolComplexity[];
  output_schema_count: number;
  annotation_coverage: McpAnnotationCoverage;
  documentation_coverage: McpDocumentationCoverage;
  metrics_fingerprint: string | null;
}

/** The insight/surface response envelope: the resolved snapshot identity plus its metrics. */
export interface McpInsightSurface {
  endpoint_id: string;
  version_id: string;
  version_seq: number;
  version_tag: string | null;
  is_current: boolean;
  metrics: McpSurfaceMetrics;
}

// --- Parsing ---------------------------------------------------------------------------------

function typeCountsFromPayload(raw: unknown): McpTypeCounts {
  const r = (raw ?? {}) as Record<string, unknown>;
  const tools = asInt(r.tools);
  const resources = asInt(r.resources);
  const resource_templates = asInt(r.resource_templates);
  const prompts = asInt(r.prompts);
  // Derive `total` from the parts so a tile row can never disagree with the counts it sums.
  const total = tools + resources + resource_templates + prompts;
  return { tools, resources, resource_templates, prompts, total };
}

function toolComplexityFromPayload(raw: unknown): McpToolComplexity {
  const r = (raw ?? {}) as Record<string, unknown>;
  return {
    name: String(r.name ?? ''),
    property_count: asInt(r.property_count),
    required_count: asInt(r.required_count),
    optional_count: asInt(r.optional_count),
    documented_property_count: asInt(r.documented_property_count),
    max_nesting_depth: asInt(r.max_nesting_depth),
    uses_enum: asBool(r.uses_enum),
    uses_one_of: asBool(r.uses_one_of),
    has_output_schema: asBool(r.has_output_schema),
  };
}

function annotationCoverageFromPayload(raw: unknown): McpAnnotationCoverage {
  const r = (raw ?? {}) as Record<string, unknown>;
  return {
    tool_count: asInt(r.tool_count),
    annotated_tools: asInt(r.annotated_tools),
    read_only_hint: asInt(r.read_only_hint),
    destructive_hint: asInt(r.destructive_hint),
    idempotent_hint: asInt(r.idempotent_hint),
    open_world_hint: asInt(r.open_world_hint),
  };
}

function documentationCoverageFromPayload(raw: unknown): McpDocumentationCoverage {
  const r = (raw ?? {}) as Record<string, unknown>;
  return {
    item_count: asInt(r.item_count),
    described_items: asInt(r.described_items),
    titled_items: asInt(r.titled_items),
    description_pct: asFloat(r.description_pct),
    title_pct: asFloat(r.title_pct),
    tool_param_count: asInt(r.tool_param_count),
    documented_tool_params: asInt(r.documented_tool_params),
    tool_param_description_pct: asFloat(r.tool_param_description_pct),
  };
}

function surfaceMetricsFromPayload(raw: unknown): McpSurfaceMetrics {
  const r = (raw ?? {}) as Record<string, unknown>;
  const toolComplexity = Array.isArray(r.tool_complexity)
    ? r.tool_complexity.map(toolComplexityFromPayload)
    : [];
  return {
    type_counts: typeCountsFromPayload(r.type_counts),
    tool_complexity: toolComplexity,
    output_schema_count: asInt(r.output_schema_count),
    annotation_coverage: annotationCoverageFromPayload(r.annotation_coverage),
    documentation_coverage: documentationCoverageFromPayload(r.documentation_coverage),
    metrics_fingerprint: asString(r.metrics_fingerprint),
  };
}

/**
 * Parse an `insight/surface` response defensively into an {@link McpInsightSurface}, or `null` when
 * the payload carries no resolvable snapshot id (a malformed or error body). Missing metric fields
 * fall back to zeroes so a partially-populated surface still renders rather than throwing.
 */
export function mcpInsightSurfaceFromPayload(data: unknown): McpInsightSurface | null {
  const r = (data ?? {}) as Record<string, unknown>;
  const versionId = asString(r.version_id);
  if (!versionId) return null;
  return {
    endpoint_id: String(r.endpoint_id ?? ''),
    version_id: versionId,
    version_seq: asInt(r.version_seq),
    version_tag: asString(r.version_tag),
    is_current: asBool(r.is_current),
    metrics: surfaceMetricsFromPayload(r.metrics),
  };
}

// --- Derived projections ---------------------------------------------------------------------

/** One capability-count tile: a stable key, its human label, and the count to show. */
export interface McpTypeCountTile {
  key: keyof Omit<McpTypeCounts, 'total'>;
  label: string;
  value: number;
}

/**
 * The four per-kind capability tiles in display order (tools → resources → resource templates →
 * prompts). The grand `total` is shown separately as the section headline, so it is not a tile.
 */
export function mcpTypeCountTiles(counts: McpTypeCounts): McpTypeCountTile[] {
  return [
    { key: 'tools', label: 'Tools', value: counts.tools },
    { key: 'resources', label: 'Resources', value: counts.resources },
    { key: 'resource_templates', label: 'Resource templates', value: counts.resource_templates },
    { key: 'prompts', label: 'Prompts', value: counts.prompts },
  ];
}

/** One documentation-coverage meter: a label, its 0-100 percentage, and the raw `have / of` counts. */
export interface McpCoverageStat {
  key: string;
  label: string;
  /** 0-100, clamped and rounded for display. */
  pct: number;
  have: number;
  of: number;
}

/**
 * The baseline documentation/coverage meters the scaffold shows for a surface: item description &
 * title coverage, tool-parameter documentation, and output-schema adoption across tools. Each
 * carries the underlying `have / of` counts so a meter can render "3 / 10" alongside its percentage
 * and a zero-denominator reads as 0% rather than NaN.
 */
export function mcpCoverageStats(metrics: McpSurfaceMetrics): McpCoverageStat[] {
  const docs = metrics.documentation_coverage;
  const tools = metrics.type_counts.tools;
  return [
    {
      key: 'described',
      label: 'Items described',
      pct: clampPct(docs.description_pct),
      have: docs.described_items,
      of: docs.item_count,
    },
    {
      key: 'titled',
      label: 'Items titled',
      pct: clampPct(docs.title_pct),
      have: docs.titled_items,
      of: docs.item_count,
    },
    {
      key: 'params',
      label: 'Tool params documented',
      pct: clampPct(docs.tool_param_description_pct),
      have: docs.documented_tool_params,
      of: docs.tool_param_count,
    },
    {
      key: 'output-schema',
      label: 'Tools with output schema',
      pct: pctOf(metrics.output_schema_count, tools),
      have: metrics.output_schema_count,
      of: tools,
    },
  ];
}

/** Clamp an incoming 0-100 percentage into range and round it for display. */
function clampPct(pct: number): number {
  if (!Number.isFinite(pct)) return 0;
  return Math.round(Math.min(100, Math.max(0, pct)));
}

/** A safe `have / of → 0-100` percentage; a zero (or missing) denominator yields 0, never NaN. */
function pctOf(have: number, of: number): number {
  if (of <= 0) return 0;
  return clampPct((have / of) * 100);
}

// --- Server profile (V2-MCP-29.1 / MCAT-15.1) ------------------------------------------------
// The at-a-glance "who is this server" identity card that heads the Insight tab. It is assembled
// from three sources the tab already holds — the endpoint record (transport, health, name), the
// selected snapshot's version summary (server identity, protocol, grade), and its capability-surface
// metrics (counts) — into one flat, React-free shape the <ServerProfileCard> renders. Every field
// degrades to `null` so an older (2025-03-26) server missing a title/output-schema, an unscored
// snapshot, or a surface that failed to load still produces a coherent card rather than throwing.

/** The flat, presentation-ready identity of an MCP server for one snapshot. */
export interface McpServerProfile {
  /** Best available display name: server `title` → server `name` → catalog endpoint name → fallback. */
  displayName: string;
  /** The catalog endpoint name, shown as a subtitle when it differs from {@link displayName}. */
  endpointName: string | null;
  /** The endpoint's connection URL, or `null` when unknown. */
  endpointUrl: string | null;
  /** The server's self-reported `version` string (e.g. `1.4.0`), or `null`. */
  serverVersion: string | null;
  /** The negotiated MCP `protocol_version` (e.g. `2025-06-18`), or `null` for older servers. */
  protocolVersion: string | null;
  /** The endpoint transport (e.g. `streamable_http`), or `null` when unknown. */
  transport: string | null;
  /** The summarized snapshot's sequence number, or `null` when no snapshot is resolved. */
  versionSeq: number | null;
  /** The snapshot's tag/date label, or `null`. */
  versionTag: string | null;
  /** True when the summarized snapshot is the endpoint's current one. */
  isCurrent: boolean;
  /** 0-100 quality score of the snapshot, or `null` when unscored. */
  score: number | null;
  /** A-F quality grade of the snapshot, or `null` when unscored. */
  grade: string | null;
  /** Per-kind capability counts from the surface, or `null` when the surface is unavailable. */
  capabilityCounts: McpTypeCounts | null;
  /** Raw last-discovery status the health pill resolves (e.g. `changed`/`failed`), or `null`. */
  discoveryStatus: string | null;
  /** ISO instant the surface last changed (this snapshot's discovery), for the recency pill. */
  lastChangedAt: string | null;
  /** The server's `instructions`, rendered prominently when present (trimmed; `null` when empty). */
  instructions: string | null;
}

/** Trim a string to `null` when it is absent or only whitespace. */
function trimmedOrNull(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Assemble the {@link McpServerProfile} the identity card renders from the sources the Insight tab
 * already holds. All inputs are optional and every derived field degrades to `null` (or the endpoint
 * fallback name) so a never-scored, partially-discovered, or older server still yields a coherent
 * card. Snapshot-level identity (name/title/version, protocol, grade, "last changed") comes from the
 * selected {@link McpVersionSummary}; endpoint-level facts (transport, discovery health) come from
 * the {@link McpEndpointDetail}; capability counts come from the {@link McpInsightSurface}.
 *
 * @param sources.endpoint      The endpoint record (transport, health, catalog name), if loaded.
 * @param sources.version       The selected snapshot's version-history summary, if resolved.
 * @param sources.surface       The snapshot's capability-surface metrics, if loaded.
 * @param sources.instructions  The server's instructions for the snapshot, when available.
 */
export function mcpServerProfileFrom(sources: {
  endpoint?: McpEndpointDetail | null;
  version?: McpVersionSummary | null;
  surface?: McpInsightSurface | null;
  instructions?: string | null;
}): McpServerProfile {
  const { endpoint, version, surface, instructions } = sources;
  const endpointName = trimmedOrNull(endpoint?.name);
  const serverTitle = trimmedOrNull(version?.server_title);
  const serverName = trimmedOrNull(version?.server_name);
  return {
    displayName: serverTitle ?? serverName ?? endpointName ?? 'MCP server',
    endpointName,
    endpointUrl: trimmedOrNull(endpoint?.endpoint_url),
    serverVersion: trimmedOrNull(version?.server_version),
    protocolVersion: trimmedOrNull(version?.protocol_version),
    transport: trimmedOrNull(endpoint?.transport),
    versionSeq: version ? version.version_seq : null,
    versionTag: trimmedOrNull(version?.version_tag),
    isCurrent: version?.is_current ?? false,
    score: version?.score ?? null,
    grade: trimmedOrNull(version?.grade),
    capabilityCounts: surface ? surface.metrics.type_counts : null,
    discoveryStatus: trimmedOrNull(endpoint?.last_discovery_status),
    lastChangedAt: version?.discovered_at ?? version?.created_at ?? null,
    instructions: trimmedOrNull(instructions),
  };
}
