'use client';

/**
 * Shared MCP UI primitives — live showcase gallery (V2-MCP-24.7 / MCAT-10.7).
 *
 * The Storybook-equivalent for this codebase (which has no Storybook): a self-contained, data-free
 * route at `/design-system/mcp` that renders every primitive in every mockup variant. It doubles as
 * a visual smoke test for the design-system foundation and as living documentation for the screens
 * (10.1 / 10.2 / 10.4 / 10.8) that consume these primitives. Paired with `docs/MCP_UI_PRIMITIVES.md`.
 */
import * as React from 'react';
import {
  GradeGlyph,
  McpBadge,
  HealthPill,
  RecencyPill,
  ServerProfileCard,
  FindingSeverity,
  DetailTabs,
  DetailTabsList,
  DetailTabsContent,
} from '@/app/components/ui/mcp';
import type { McpServerProfile, McpToolComplexity } from '@/app/components/ade/dashboard/mcp/mcpInsightUi';
import type { McpCapabilityItem } from '@/app/components/ade/dashboard/mcp/mcpBrowseUi';
import { ToolComplexityPanel } from '@/app/components/ui/mcp/ToolComplexityPanel';
import { SafetyPosturePanel } from '@/app/components/ui/mcp/SafetyPosturePanel';
import { DocCoveragePanel } from '@/app/components/ui/mcp/DocCoveragePanel';
import { CapabilityChurnPanel } from '@/app/components/ui/mcp/CapabilityChurnPanel';
import { GradeSurfaceTrendPanel } from '@/app/components/ui/mcp/GradeSurfaceTrendPanel';
import type { McpEvolutionPoint } from '@/app/components/ade/dashboard/mcp/mcpEvolutionUi';
import { CapabilityPresenceMatrixPanel } from '@/app/components/ui/mcp/CapabilityPresenceMatrixPanel';
import { ChangedSinceDigestPanel } from '@/app/components/ui/mcp/ChangedSinceDigestPanel';
import { DiscoveryHealthPanel } from '@/app/components/ui/mcp/DiscoveryHealthPanel';
import { ToolLatencyPanel } from '@/app/components/ui/mcp/ToolLatencyPanel';
import { ScoreBreakdownPanel } from '@/app/components/ui/mcp/ScoreBreakdownPanel';
import { TrustProfilePanel } from '@/app/components/ui/mcp/TrustProfilePanel';
import {
  mcpReliabilityHealthFromPayload,
  mcpToolReliabilityFromPayload,
  type McpDiscoveryHealth,
  type McpToolReliability,
} from '@/app/components/ade/dashboard/mcp/mcpReliabilityUi';
import {
  mcpLintReportFromPayload,
  type McpLintReport,
} from '@/app/components/ade/dashboard/mcp/mcpLintUi';
import {
  mcpTrustProfileFromPayload,
  type McpTrustProfile,
} from '@/app/components/ade/dashboard/mcp/mcpTrustUi';
import {
  mcpDigestFromPayload,
  type McpEndpointDigest,
} from '@/app/components/ade/dashboard/mcp/mcpDigestUi';
import type { McpVersionDetail } from '@/app/components/ade/dashboard/mcp/mcpBrowseUi';
// The Monaco-backed code-viewer primitives were promoted out of `ui/mcp` to the format-neutral
// `ui/code` module (MFI-28.7); the gallery documents them under those neutral names.
import { JsonViewer, JsonDiffViewer, Disclosure } from '@/app/components/ui/code';
// Token-driven SVG chart kit (V2-MCP-28.3).
import {
  Sparkline,
  TrendLine,
  BarSeries,
  Donut,
  StackedTimeline,
  Radar,
  Heatmap,
  Gauge,
} from '@/app/components/ui/mcp';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { MCP_DETAIL_TABS } from '@/app/components/ade/dashboard/mcp/mcpUiPrimitives';
import { Server } from 'lucide-react';

/** A labelled gallery section. */
function Section({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{title}</h2>
      <p className="mb-4 mt-1 text-sm text-gray-500 dark:text-gray-400">{description}</p>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </section>
  );
}

const NOW = Date.parse('2026-06-27T12:00:00Z');

/** A fully-populated modern server (title, protocol, grade, counts, instructions). */
const PROFILE_FULL: McpServerProfile = {
  displayName: 'Acme Search',
  endpointName: 'acme-search-prod',
  endpointUrl: 'https://mcp.acme.dev/search',
  serverVersion: '1.4.0',
  protocolVersion: '2025-06-18',
  transport: 'streamable_http',
  versionSeq: 7,
  versionTag: '2026-06-27',
  isCurrent: true,
  score: 92,
  grade: 'A',
  capabilityCounts: { tools: 8, resources: 3, resource_templates: 1, prompts: 2, total: 14 },
  discoveryStatus: 'changed',
  lastChangedAt: '2026-06-27T10:00:00Z',
  instructions:
    'Use `search` for free-text queries and `fetch` to retrieve a document by id. Prefer narrow ' +
    'filters; results are capped at 100.',
};

/** An older (2025-03-26) server missing title/protocol/output-schema — the graceful-degrade path. */
const PROFILE_LEGACY: McpServerProfile = {
  displayName: 'legacy-notes',
  endpointName: 'legacy-notes',
  endpointUrl: 'https://old.example.com/mcp',
  serverVersion: null,
  protocolVersion: null,
  transport: 'http+sse',
  versionSeq: 2,
  versionTag: null,
  isCurrent: false,
  score: 58,
  grade: 'D',
  capabilityCounts: { tools: 3, resources: 0, resource_templates: 0, prompts: 0, total: 3 },
  discoveryStatus: 'unchanged',
  lastChangedAt: '2026-05-20T09:00:00Z',
  instructions: null,
};

/** An unscored, never-discovered endpoint — no grade, no counts, unknown health. */
const PROFILE_UNSCORED: McpServerProfile = {
  displayName: 'staging-gateway',
  endpointName: 'staging-gateway',
  endpointUrl: 'https://staging.example.com/mcp',
  serverVersion: null,
  protocolVersion: null,
  transport: 'streamable_http',
  versionSeq: null,
  versionTag: null,
  isCurrent: false,
  score: null,
  grade: null,
  capabilityCounts: null,
  discoveryStatus: null,
  lastChangedAt: null,
  instructions: null,
};

/** A representative tool-complexity set spanning the tiers, incl. a bare tool and a deep polymorphic one. */
const TOOL_COMPLEXITY_SAMPLE: McpToolComplexity[] = [
  {
    name: 'ping',
    property_count: 0,
    required_count: 0,
    optional_count: 0,
    documented_property_count: 0,
    max_nesting_depth: 0,
    uses_enum: false,
    uses_one_of: false,
    has_output_schema: false,
  },
  {
    name: 'search',
    property_count: 3,
    required_count: 1,
    optional_count: 2,
    documented_property_count: 3,
    max_nesting_depth: 1,
    uses_enum: true,
    uses_one_of: false,
    has_output_schema: true,
  },
  {
    name: 'update_record',
    property_count: 7,
    required_count: 3,
    optional_count: 4,
    documented_property_count: 4,
    max_nesting_depth: 2,
    uses_enum: false,
    uses_one_of: false,
    has_output_schema: false,
  },
  {
    name: 'orchestrate_workflow',
    property_count: 12,
    required_count: 4,
    optional_count: 8,
    documented_property_count: 6,
    max_nesting_depth: 5,
    uses_enum: true,
    uses_one_of: true,
    has_output_schema: true,
  },
];

/** A helper to build a `tool` capability item for the safety-panel gallery samples. */
function galleryTool(name: string, annotations: Record<string, unknown> | null): McpCapabilityItem {
  return {
    item_type: 'tool',
    name,
    title: null,
    description: null,
    uri: null,
    uri_template: null,
    input_schema: null,
    output_schema: null,
    annotations,
    ordinal: 0,
  };
}

/** A representative surface spanning read-only, destructive, open-world, and unannotated tools. */
const SAFETY_TOOLS_SAMPLE: McpCapabilityItem[] = [
  galleryTool('search', { readOnlyHint: true, destructiveHint: false }),
  galleryTool('read_file', { readOnlyHint: true, idempotentHint: true }),
  galleryTool('sync_index', { idempotentHint: true }),
  galleryTool('delete_record', { destructiveHint: true, openWorldHint: true }),
  galleryTool('run_query', null),
];

/** A surface whose tools declare no hints at all — the "treat with caution" state. */
const SAFETY_TOOLS_UNANNOTATED: McpCapabilityItem[] = [
  galleryTool('do_thing', null),
  galleryTool('do_other', {}),
];

/** A mixed-documentation surface for the coverage gauges: some items/params documented, some not. */
const DOC_COVERAGE_SAMPLE: McpCapabilityItem[] = [
  {
    item_type: 'tool',
    name: 'search',
    title: 'Search',
    description: 'Full-text search over the catalog.',
    uri: null,
    uri_template: null,
    input_schema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'The text to search for.' },
        limit: { type: 'number' },
      },
    },
    output_schema: { type: 'object' },
    annotations: null,
    ordinal: 0,
  },
  {
    item_type: 'tool',
    name: 'delete_record',
    title: null,
    description: null,
    uri: null,
    uri_template: null,
    input_schema: { type: 'object', properties: { id: { type: 'string' } } },
    output_schema: null,
    annotations: null,
    ordinal: 1,
  },
  {
    item_type: 'resource',
    name: 'catalog_index',
    title: 'Catalog index',
    description: 'The full catalog index resource.',
    uri: 'catalog://index',
    uri_template: null,
    input_schema: null,
    output_schema: null,
    annotations: null,
    ordinal: 2,
  },
];

/** A four-snapshot evolution series for the CapabilityChurnPanel demo (V2-MCP-30.1). */
const CHURN_SERIES_SAMPLE: McpEvolutionPoint[] = [
  {
    version_id: 'demo-v1',
    version_seq: 1,
    version_tag: '2026-05-01',
    discovered_at: '2026-05-01T10:00:00Z',
    is_current: false,
    type_counts: { tools: 8, resources: 0, resource_templates: 0, prompts: 0, total: 8 },
    score: 70,
    grade: 'C',
    change_counts: { added: 8, removed: 0, modified: 0, total: 8 },
    severity_counts: { breaking: 0, additive: 8, review: 0, total: 8 },
  },
  {
    // A quiet release — no churn, but still a column on the axis.
    version_id: 'demo-v2',
    version_seq: 2,
    version_tag: '2026-05-20',
    discovered_at: '2026-05-20T10:00:00Z',
    is_current: false,
    type_counts: { tools: 8, resources: 0, resource_templates: 0, prompts: 0, total: 8 },
    score: 72,
    grade: 'C',
    change_counts: { added: 0, removed: 0, modified: 0, total: 0 },
    severity_counts: { breaking: 0, additive: 0, review: 0, total: 0 },
  },
  {
    // The busiest release — and a breaking one (2 removed capabilities).
    version_id: 'demo-v3',
    version_seq: 3,
    version_tag: '2026-06-15',
    discovered_at: '2026-06-15T10:00:00Z',
    is_current: false,
    type_counts: { tools: 9, resources: 2, resource_templates: 0, prompts: 0, total: 11 },
    score: 84,
    grade: 'B',
    change_counts: { added: 3, removed: 2, modified: 4, total: 9 },
    severity_counts: { breaking: 2, additive: 5, review: 2, total: 9 },
  },
  {
    version_id: 'demo-v4',
    version_seq: 4,
    version_tag: '2026-07-06',
    discovered_at: '2026-07-06T10:00:00Z',
    is_current: true,
    type_counts: { tools: 11, resources: 2, resource_templates: 1, prompts: 1, total: 15 },
    score: 90,
    grade: 'A',
    change_counts: { added: 5, removed: 0, modified: 1, total: 6 },
    severity_counts: { breaking: 0, additive: 6, review: 0, total: 6 },
  },
];

/** Sample digests for the ChangedSinceDigestPanel demo (V2-MCP-30.5): the three display states. */
const DIGEST_CHANGED_SAMPLE: McpEndpointDigest = mcpDigestFromPayload({
  success: true,
  endpoint_id: 'digest-ep',
  new_to_you: false,
  has_changes: true,
  last_seen_version_id: 'digest-v2',
  last_seen_version_seq: 2,
  last_seen_at: '2026-06-01T10:00:00Z',
  current_version_id: 'digest-v4',
  current_version_seq: 4,
  current_version_tag: '2026-07-06',
  current_type_counts: { tools: 9, resources: 3, resource_templates: 0, prompts: 2, total: 14 },
  change_counts: { added: 2, removed: 1, modified: 2, total: 5 },
  severity_counts: { breaking: 1, additive: 2, review: 2, total: 5 },
  changes: [
    { change_type: 'removed', item_type: 'tool', item_name: 'legacy_search', severity: 'breaking' },
    { change_type: 'added', item_type: 'tool', item_name: 'summarize', severity: 'additive' },
    { change_type: 'added', item_type: 'resource', item_name: 'docs://guide', severity: 'additive' },
    { change_type: 'modified', item_type: 'tool', item_name: 'forecast', severity: 'review' },
    { change_type: 'modified', item_type: 'prompt', item_name: 'triage', severity: 'review' },
  ],
})!;

const DIGEST_NEW_SAMPLE: McpEndpointDigest = mcpDigestFromPayload({
  success: true,
  endpoint_id: 'digest-ep',
  new_to_you: true,
  has_changes: false,
  last_seen_version_id: null,
  last_seen_version_seq: null,
  last_seen_at: null,
  current_version_id: 'digest-v4',
  current_version_seq: 4,
  current_version_tag: '2026-07-06',
  current_type_counts: { tools: 9, resources: 3, resource_templates: 0, prompts: 2, total: 14 },
  change_counts: { added: 0, removed: 0, modified: 0, total: 0 },
  severity_counts: { breaking: 0, additive: 0, review: 0, total: 0 },
  changes: [],
})!;

const DIGEST_CURRENT_SAMPLE: McpEndpointDigest = mcpDigestFromPayload({
  success: true,
  endpoint_id: 'digest-ep',
  new_to_you: false,
  has_changes: false,
  last_seen_version_id: 'digest-v4',
  last_seen_version_seq: 4,
  last_seen_at: '2026-07-06T10:00:00Z',
  current_version_id: 'digest-v4',
  current_version_seq: 4,
  current_version_tag: '2026-07-06',
  current_type_counts: { tools: 9, resources: 3, resource_templates: 0, prompts: 2, total: 14 },
  change_counts: { added: 0, removed: 0, modified: 0, total: 0 },
  severity_counts: { breaking: 0, additive: 0, review: 0, total: 0 },
  changes: [],
})!;

/** A discovery-job for the health-timeline demos (V2-MCP-31.1). */
function healthJob(
  jobId: string,
  state: string,
  outcome: string,
  createdAt: string,
  errorCode: string | null = null,
): Record<string, unknown> {
  return {
    job_id: jobId,
    state,
    trigger: 'sweep',
    outcome,
    error_code: errorCode,
    created_at: createdAt,
    started_at: createdAt,
    finished_at: createdAt,
    duration_ms: state === 'failed' ? null : 420,
  };
}

/** A mostly-healthy endpoint (one auth blip): timeline newest-first, ~86% available. */
const HEALTH_HEALTHY_SAMPLE: McpDiscoveryHealth = mcpReliabilityHealthFromPayload({
  health: {
    timeline: [
      healthJob('h7', 'completed', 'ok', '2026-07-06T12:00:00Z'),
      healthJob('h6', 'completed', 'ok', '2026-07-06T06:00:00Z'),
      healthJob('h5', 'failed', 'auth_required', '2026-07-06T00:00:00Z', 'auth_required'),
      healthJob('h4', 'completed', 'ok', '2026-07-05T18:00:00Z'),
      healthJob('h3', 'completed', 'ok', '2026-07-05T12:00:00Z'),
      healthJob('h2', 'completed', 'ok', '2026-07-05T06:00:00Z'),
      healthJob('h1', 'completed', 'ok', '2026-07-05T00:00:00Z'),
    ],
    window: 50,
    last_status: 'unchanged',
    last_discovered_at: '2026-07-06T12:00:00Z',
  },
})!;

/** A quarantined endpoint (repeated connect failures): the panel flags the auto-disable banner. */
const HEALTH_QUARANTINED_SAMPLE: McpDiscoveryHealth = mcpReliabilityHealthFromPayload({
  health: {
    timeline: [
      healthJob('q4', 'failed', 'connect_error', '2026-07-06T12:00:00Z', 'connect_error'),
      healthJob('q3', 'failed', 'connect_error', '2026-07-06T06:00:00Z', 'connect_error'),
      healthJob('q2', 'failed', 'timeout', '2026-07-06T00:00:00Z', 'timeout'),
      healthJob('q1', 'completed', 'ok', '2026-07-05T18:00:00Z'),
    ],
    window: 50,
    quarantined: true,
    quarantined_at: '2026-07-06T12:00:00Z',
    quarantine_reason: 'connect_error: connection refused',
    consecutive_failures: 3,
    last_status: 'connect_error',
    last_discovered_at: '2026-07-06T12:00:00Z',
  },
})!;

/** A never-discovered endpoint: empty timeline → the panel's empty state. */
const HEALTH_EMPTY_SAMPLE: McpDiscoveryHealth = mcpReliabilityHealthFromPayload({
  health: { timeline: [], window: 50 },
})!;

/** One per-tool reliability row for the tool-latency demos (V2-MCP-31.2). */
function toolStat(
  name: string,
  callCount: number,
  errorCount: number,
  p50: number,
  p95: number,
  p99: number,
): Record<string, unknown> {
  return {
    tool_name: name,
    call_count: callCount,
    error_count: errorCount,
    success_count: callCount - errorCount,
    error_rate: callCount ? errorCount / callCount : 0,
    latency: { count: callCount, avg_ms: p50, min_ms: p50, max_ms: p99, p50_ms: p50, p95_ms: p95, p99_ms: p99 },
  };
}

/** A tested server with a fast, reliable tool and a slow, flaky one. */
const TOOLS_POPULATED_SAMPLE: McpToolReliability = mcpToolReliabilityFromPayload({
  tools: {
    tools: [
      toolStat('search', 42, 1, 45, 120, 180),
      toolStat('geocode', 30, 0, 12, 28, 40),
      toolStat('write_record', 8, 3, 640, 1200, 1500),
      toolStat('summarize', 15, 2, 320, 780, 900),
    ],
    latency_distribution: [
      { label: '0–50 ms', upper_ms: 50, count: 40 },
      { label: '50–100 ms', upper_ms: 100, count: 22 },
      { label: '100–250 ms', upper_ms: 250, count: 18 },
      { label: '250–500 ms', upper_ms: 500, count: 9 },
      { label: '500 ms–1 s', upper_ms: 1000, count: 4 },
      { label: '1–2.5 s', upper_ms: 2500, count: 2 },
      { label: '2.5 s+', upper_ms: null, count: 0 },
    ],
    window_days: 30,
  },
})!;

/** A never-tested endpoint: no tool calls → the panel's empty state. */
const TOOLS_EMPTY_SAMPLE: McpToolReliability = mcpToolReliabilityFromPayload({
  tools: { tools: [], latency_distribution: [], window_days: 30 },
})!;

/** One lint finding for the score-breakdown demo. */
function lintFinding(
  id: string,
  path: string,
  category: string,
  rule: string,
  severity: string,
  message: string,
) {
  return { id, path, category, rule, severity, message };
}

/** A scored snapshot with a spread of findings across rule groups — the populated breakdown demo. */
const REPORT_POPULATED_SAMPLE: McpLintReport = mcpLintReportFromPayload({
  endpointId: 'ep-demo',
  versionId: 'v-demo',
  versionSeq: 7,
  versionTag: '2026-07-01',
  score: 72,
  grade: 'C',
  findings: [
    lintFinding('f1', 'tools.write_record', 'security', 'security.destructive-no-auth', 'error', 'Destructive tool reachable with no authentication.'),
    lintFinding('f2', 'tools.search', 'annotation', 'annotation.missing-read-only-hint', 'warning', 'Read-only tool is missing its readOnlyHint annotation.'),
    lintFinding('f3', 'tools.geocode', 'annotation', 'annotation.missing-read-only-hint', 'warning', 'Read-only tool is missing its readOnlyHint annotation.'),
    lintFinding('f4', 'tools.SearchRecords', 'naming', 'naming.item-name-not-snake-case', 'warning', 'Tool name is not snake_case.'),
    lintFinding('f5', 'resources.data', 'structure', 'structure.missing-description', 'info', 'Resource has no description.'),
    lintFinding('f6', 'tools.summarize', 'hygiene', 'hygiene.trailing-whitespace', 'info', 'Description has trailing whitespace.'),
  ],
  ruleHits: {
    'security.destructive-no-auth': 1,
    'annotation.missing-read-only-hint': 2,
    'naming.item-name-not-snake-case': 1,
    'structure.missing-description': 1,
    'hygiene.trailing-whitespace': 1,
  },
  severityCounts: { error: 1, warning: 3, info: 2 },
  reportFingerprint: 'demo-fingerprint',
  source: 'stored',
  scoredAt: '2026-07-01T00:00:00Z',
})!;

/** A clean snapshot: full marks, no findings → the panel's "clean bill of health" state. */
const REPORT_CLEAN_SAMPLE: McpLintReport = mcpLintReportFromPayload({
  endpointId: 'ep-demo',
  versionId: 'v-clean',
  versionSeq: 8,
  versionTag: '2026-07-05',
  score: 100,
  grade: 'A',
  findings: [],
  ruleHits: {},
  severityCounts: { error: 0, warning: 0, info: 0 },
  reportFingerprint: 'demo-clean',
  source: 'stored',
  scoredAt: '2026-07-05T00:00:00Z',
})!;

/**
 * A partially-measured composite trust profile (V2-MCP-31.4): three axes scored across the bands
 * (a strong quality, a fair safety, a weak documentation) and two **gaps** — a never-changed server
 * (stability) and a never-tested one (responsiveness) — that render as explicit gaps, not zeros.
 */
const TRUST_POPULATED_SAMPLE: McpTrustProfile = mcpTrustProfileFromPayload({
  success: true,
  endpoint_id: 'ep-demo',
  version_id: 'v-demo',
  auth_type: 'none',
  profile: {
    axes: [
      { key: 'quality', label: 'Quality', value: 88, available: true, detail: 'Grade B · 88/100', methodology: "The server's latest automated quality grade (0–100) from the MCP lint scorer." },
      { key: 'safety', label: 'Safety', value: 62, available: true, detail: '3/5 tools annotated · 1 destructive with no auth', methodology: 'Half from behavioural-annotation coverage, half from guardedness against destructive tools reachable with no auth.' },
      { key: 'documentation', label: 'Documentation', value: 40, available: true, detail: '40% described · 20% titled', methodology: 'The average of how documented the surface is: descriptions, titles, and tool-parameter docs.' },
      { key: 'stability', label: 'Stability', value: null, available: false, detail: 'Not enough history', methodology: 'The share of surface changes across snapshots that were non-breaking. Needs at least two snapshots.' },
      { key: 'responsiveness', label: 'Responsiveness', value: null, available: false, detail: 'Never tested', methodology: 'Half from the test-invocation success rate, half from p95 latency. Needs the server to have been tested.' },
    ],
    overall: 63,
    available_count: 3,
    axis_count: 5,
  },
})!;

/** A never-measured endpoint: every axis is a gap → the panel's "not enough signal yet" state. */
const TRUST_EMPTY_SAMPLE: McpTrustProfile = mcpTrustProfileFromPayload({
  success: true,
  endpoint_id: 'ep-demo',
  version_id: null,
  auth_type: null,
  profile: {
    axes: [
      { key: 'quality', label: 'Quality', value: null, available: false, detail: 'Not yet scored', methodology: 'The server’s latest automated quality grade.' },
      { key: 'safety', label: 'Safety', value: null, available: false, detail: 'No tools to assess', methodology: 'Annotation coverage crossed with the destructive/auth posture.' },
      { key: 'documentation', label: 'Documentation', value: null, available: false, detail: 'No capabilities to assess', methodology: 'How documented the surface is.' },
      { key: 'stability', label: 'Stability', value: null, available: false, detail: 'Not enough history', methodology: 'The non-breaking-change rate across snapshots.' },
      { key: 'responsiveness', label: 'Responsiveness', value: null, available: false, detail: 'Never tested', methodology: 'Test-invocation success rate + latency.' },
    ],
    overall: null,
    available_count: 0,
    axis_count: 5,
  },
})!;

/**
 * A five-snapshot series for the GradeSurfaceTrendPanel demo (V2-MCP-30.4): a rising score, one
 * **unscored** snapshot (v3 — its score gaps, is not zeroed), and one breaking release (v4).
 */
const TREND_SERIES_SAMPLE: McpEvolutionPoint[] = [
  {
    version_id: 'trend-v1',
    version_seq: 1,
    version_tag: '2026-04-01',
    discovered_at: '2026-04-01T10:00:00Z',
    is_current: false,
    type_counts: { tools: 6, resources: 0, resource_templates: 0, prompts: 0, total: 6 },
    score: 62,
    grade: 'D',
    change_counts: { added: 6, removed: 0, modified: 0, total: 6 },
    severity_counts: { breaking: 0, additive: 6, review: 0, total: 6 },
  },
  {
    version_id: 'trend-v2',
    version_seq: 2,
    version_tag: '2026-04-20',
    discovered_at: '2026-04-20T10:00:00Z',
    is_current: false,
    type_counts: { tools: 8, resources: 1, resource_templates: 0, prompts: 0, total: 9 },
    score: 74,
    grade: 'C',
    change_counts: { added: 3, removed: 0, modified: 1, total: 4 },
    severity_counts: { breaking: 0, additive: 3, review: 1, total: 4 },
  },
  {
    // An unscored snapshot — the score line gaps across it rather than dropping to zero.
    version_id: 'trend-v3',
    version_seq: 3,
    version_tag: '2026-05-10',
    discovered_at: '2026-05-10T10:00:00Z',
    is_current: false,
    type_counts: { tools: 8, resources: 1, resource_templates: 0, prompts: 0, total: 9 },
    score: null,
    grade: null,
    change_counts: { added: 0, removed: 0, modified: 0, total: 0 },
    severity_counts: { breaking: 0, additive: 0, review: 0, total: 0 },
  },
  {
    // A breaking release — two capabilities removed (marker overlaid on the timeline).
    version_id: 'trend-v4',
    version_seq: 4,
    version_tag: '2026-06-01',
    discovered_at: '2026-06-01T10:00:00Z',
    is_current: false,
    type_counts: { tools: 7, resources: 1, resource_templates: 0, prompts: 1, total: 9 },
    score: 80,
    grade: 'B',
    change_counts: { added: 2, removed: 2, modified: 1, total: 5 },
    severity_counts: { breaking: 2, additive: 2, review: 1, total: 5 },
  },
  {
    version_id: 'trend-v5',
    version_seq: 5,
    version_tag: '2026-07-06',
    discovered_at: '2026-07-06T10:00:00Z',
    is_current: true,
    type_counts: { tools: 9, resources: 2, resource_templates: 1, prompts: 1, total: 13 },
    score: 91,
    grade: 'A',
    change_counts: { added: 4, removed: 0, modified: 0, total: 4 },
    severity_counts: { breaking: 0, additive: 4, review: 0, total: 4 },
  },
];

/** A compact capability item for the presence-matrix demo (fields the matrix ignores stay null). */
function demoItem(
  item_type: string,
  name: string,
  overrides: Partial<McpCapabilityItem> = {},
): McpCapabilityItem {
  return {
    item_type,
    name,
    title: null,
    description: null,
    uri: null,
    uri_template: null,
    input_schema: null,
    output_schema: null,
    annotations: null,
    ordinal: 0,
    ...overrides,
  };
}

/** A compact version snapshot carrying only the fields the presence matrix reads. */
function demoVersion(id: string, seq: number, isCurrent: boolean, items: McpCapabilityItem[]): McpVersionDetail {
  return {
    id,
    version_seq: seq,
    version_tag: null,
    server_name: null,
    server_version: null,
    server_title: null,
    protocol_version: null,
    instructions: null,
    score: null,
    grade: null,
    is_current: isCurrent,
    discovered_at: null,
    items,
  };
}

/**
 * A four-snapshot surface for the CapabilityPresenceMatrixPanel demo (V2-MCP-30.2): a stable tool
 * present throughout, a tool whose schema is modified midway, a tool removed after v2, a volatile tool
 * that disappears then returns, a resource, and a brand-new prompt in the current snapshot.
 */
const PRESENCE_MATRIX_SAMPLE: McpVersionDetail[] = [
  demoVersion('demo-v1', 1, false, [
    demoItem('tool', 'search', { input_schema: { q: 'string' } }),
    demoItem('tool', 'legacy_export'),
    demoItem('tool', 'flaky_beta'),
    demoItem('resource', 'catalog', { uri: 'res://catalog' }),
  ]),
  demoVersion('demo-v2', 2, false, [
    demoItem('tool', 'search', { input_schema: { q: 'string' } }),
    demoItem('tool', 'legacy_export'),
    demoItem('resource', 'catalog', { uri: 'res://catalog' }),
  ]),
  demoVersion('demo-v3', 3, false, [
    // search's schema changes → modified; flaky_beta returns after a gap → volatile.
    demoItem('tool', 'search', { input_schema: { q: 'string', limit: 'number' } }),
    demoItem('tool', 'flaky_beta'),
    demoItem('resource', 'catalog', { uri: 'res://catalog' }),
  ]),
  demoVersion('demo-v4', 4, true, [
    demoItem('tool', 'search', { input_schema: { q: 'string', limit: 'number' } }),
    demoItem('tool', 'flaky_beta'),
    demoItem('resource', 'catalog', { uri: 'res://catalog' }),
    demoItem('prompt', 'summarize'),
  ]),
];

export default function McpPrimitivesShowcase() {
  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">MCP UI primitives</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          The shared, token-driven component library every MCP catalog screen reuses (V2-MCP-24.7).
        </p>
      </header>

      <Section
        title="GradeGlyph — glyph"
        description="The A–F + 0–100 lead signal on cards and headers. Size sm/md/lg; unscored falls back to a neutral chip."
      >
        <GradeGlyph grade="A" score={96} />
        <GradeGlyph grade="B" score={82} />
        <GradeGlyph grade="C" score={64} />
        <GradeGlyph grade="D" score={45} />
        <GradeGlyph grade="F" score={20} />
        <GradeGlyph size="sm" grade="B" score={82} />
        <GradeGlyph size="lg" grade="A" score={91} />
        <GradeGlyph />
      </Section>

      <Section
        title="GradeGlyph — gauge"
        description="The same color language as a 0–100 ring, used as the headline on the Lint & Score tab."
      >
        <GradeGlyph variant="gauge" size="md" grade="A" score={94} />
        <GradeGlyph variant="gauge" size="md" grade="C" score={61} />
        <GradeGlyph variant="gauge" size="md" grade="F" score={18} />
      </Section>

      <Section
        title="McpBadge — tones"
        description="The seven-tone badge that backs transport, visibility, auth, and capability-annotation chips."
      >
        <McpBadge tone="indigo">Private</McpBadge>
        <McpBadge tone="green">Public</McpBadge>
        <McpBadge tone="slate">streamable_http</McpBadge>
        <McpBadge tone="slate">http+sse (legacy)</McpBadge>
        <McpBadge tone="green">bearer</McpBadge>
        <McpBadge tone="violet">OAuth 2.1</McpBadge>
        <McpBadge tone="green">readOnly</McpBadge>
        <McpBadge tone="blue">idempotent</McpBadge>
        <McpBadge tone="red">destructive</McpBadge>
        <McpBadge tone="amber">openWorld</McpBadge>
      </Section>

      <Section title="HealthPill" description="Endpoint reachability distilled to a colored dot + label.">
        <HealthPill status="healthy" />
        <HealthPill status="degraded" />
        <HealthPill status="unreachable" />
        <HealthPill status="unknown" />
        <HealthPill status="healthy" dotOnly />
      </Section>

      <Section title="RecencyPill" description="The 'last discovered …' recency chip (relative span; deterministic here via nowMs).">
        <RecencyPill timestamp="2026-06-27T11:59:30Z" nowMs={NOW} />
        <RecencyPill timestamp="2026-06-27T10:00:00Z" nowMs={NOW} />
        <RecencyPill timestamp="2026-06-24T12:00:00Z" nowMs={NOW} />
        <RecencyPill timestamp={null} nowMs={NOW} />
      </Section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            ServerProfileCard (V2-MCP-29.1)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            The at-a-glance server identity that heads the endpoint Insight tab: name/title/version,
            protocol, transport, grade, capability counts, discovery health, a
            &ldquo;surface changed&rdquo; recency, a compact trust snapshot, and instructions when
            present. Shown fully populated,
            degraded for an older server missing title/protocol, and unscored/never-discovered.
          </p>
        </div>
        <ServerProfileCard profile={PROFILE_FULL} trustHref="#insight-reliability" nowMs={NOW} />
        <ServerProfileCard profile={PROFILE_LEGACY} nowMs={NOW} />
        <ServerProfileCard profile={PROFILE_UNSCORED} nowMs={NOW} />
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            ToolComplexityPanel (V2-MCP-29.3)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Per-tool schema &ldquo;shape&rdquo; cards driven by the 14.1 metrics — parameter count,
            required/optional split (mini bar), nesting depth, <code>enum</code>/<code>oneOf</code>
            presence, and output-schema declaration — plus a tier-distribution histogram and a
            sortable/filterable most-vs-least-complex view. A no-parameter tool and a deep polymorphic
            one both render sanely.
          </p>
        </div>
        <ToolComplexityPanel tools={TOOL_COMPLEXITY_SAMPLE} loading={false} error={null} />
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            SafetyPosturePanel (V2-MCP-29.4)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            The per-tool behavioural-hint matrix (read-only / destructive / idempotent / open-world),
            a posture headline, and the auth cross-reference. On an anonymous endpoint the destructive
            tool is flagged as reachable with no auth; a hint-less surface renders an explicit
            &ldquo;unannotated — treat with caution&rdquo; state.
          </p>
        </div>
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Anonymous endpoint (destructive + no-auth flagged)
        </div>
        <SafetyPosturePanel items={SAFETY_TOOLS_SAMPLE} authType="none" loading={false} error={null} />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Authenticated endpoint (bearer)
        </div>
        <SafetyPosturePanel items={SAFETY_TOOLS_SAMPLE} authType="bearer" loading={false} error={null} />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Fully unannotated surface
        </div>
        <SafetyPosturePanel items={SAFETY_TOOLS_UNANNOTATED} authType="bearer" loading={false} error={null} />
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            DocCoveragePanel (V2-MCP-29.5)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            A gauge row for a snapshot&apos;s documentation quality — % of items described / titled, %
            of tool parameters documented, and output-schema adoption. Each gauge drills down to the
            specific under-documented items; a tool-less surface renders an explicit N/A rather than a
            misleading 0%.
          </p>
        </div>
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Mixed coverage (drill-downs populated)
        </div>
        <DocCoveragePanel items={DOC_COVERAGE_SAMPLE} loading={false} error={null} />
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            CapabilityChurnPanel (V2-MCP-30.1)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            A stacked timeline of added / removed / modified per discovery snapshot — how much a server
            churns and when. A zero-churn version still gets its slot on the axis, the busiest release
            is called out, and clicking any column deep-links to that version&apos;s diff. Built on the
            interactive <code>StackedTimeline</code> primitive.
          </p>
        </div>
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Four snapshots (one quiet release, one high-churn)
        </div>
        <CapabilityChurnPanel
          series={CHURN_SERIES_SAMPLE}
          loading={false}
          error={null}
          onSelectVersion={() => {}}
        />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          No history yet
        </div>
        <CapabilityChurnPanel series={[]} loading={false} error={null} onSelectVersion={() => {}} />
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            CapabilityPresenceMatrixPanel (V2-MCP-30.2)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            A &quot;gantt of the surface&quot;: rows are every capability ever seen, columns are
            discovery snapshots, and each cell is added / present / modified / absent. Reveals volatile
            vs long-lived tools at a glance, badges each row&apos;s lifespan, and deep-links a column to
            its diff. Presence is reconstructed from the per-version capability items; the matrix
            scrolls (sticky header + first column) for many items.
          </p>
        </div>
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Four snapshots (a stable, a modified, a removed, a volatile, and a new capability)
        </div>
        <CapabilityPresenceMatrixPanel
          versions={PRESENCE_MATRIX_SAMPLE}
          loading={false}
          error={null}
          onSelectVersion={() => {}}
        />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          No capabilities to chart
        </div>
        <CapabilityPresenceMatrixPanel
          versions={[]}
          loading={false}
          error={null}
          onSelectVersion={() => {}}
        />
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            GradeSurfaceTrendPanel (V2-MCP-30.4)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Is the server improving? Two <code>TrendLine</code> charts across discovery snapshots — the
            quality score (0–100 / A–F) and the capability count — with breaking-change releases
            (MCAT-16.3) overlaid as markers and listed as chips that deep-link to their diff. An{' '}
            <strong>unscored</strong> snapshot is gapped, not zeroed.
          </p>
        </div>
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Five snapshots (one unscored gap, one breaking release)
        </div>
        <GradeSurfaceTrendPanel
          series={TREND_SERIES_SAMPLE}
          loading={false}
          error={null}
          onSelectVersion={() => {}}
        />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          No history yet
        </div>
        <GradeSurfaceTrendPanel
          series={[]}
          loading={false}
          error={null}
          onSelectVersion={() => {}}
        />
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            ChangedSinceDigestPanel (V2-MCP-30.5)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            A per-user &ldquo;changed since last view&rdquo; digest at the top of the Insight tab. Diffs the
            version the user last saw against the current one and classifies the delta by breaking
            severity (MCAT-16.3): a breaking-change callout, per-severity / per-direction tallies, the
            changed items, and a <code>Review changes</code> deep-link. Has three states.
          </p>
        </div>
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Changed (one breaking removal, two additive, two review)
        </div>
        <ChangedSinceDigestPanel
          digest={DIGEST_CHANGED_SAMPLE}
          loading={false}
          error={null}
          onReviewChanges={() => {}}
        />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">New to you</div>
        <ChangedSinceDigestPanel
          digest={DIGEST_NEW_SAMPLE}
          loading={false}
          error={null}
          onReviewChanges={() => {}}
        />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">Up to date</div>
        <ChangedSinceDigestPanel
          digest={DIGEST_CURRENT_SAMPLE}
          loading={false}
          error={null}
          onReviewChanges={() => {}}
        />
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            DiscoveryHealthPanel (V2-MCP-31.1)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Has the server been reachable over time? A <code>StackedTimeline</code> status strip of
            each recent discovery attempt&apos;s outcome (ok / unreachable / auth_error / …), an{' '}
            <strong>availability %</strong> over the window, a per-code failure breakdown, and a
            prominent banner when the endpoint is <strong>quarantined</strong> after repeated
            failures. Has healthy, quarantined, and empty states.
          </p>
        </div>
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Healthy (one auth blip)
        </div>
        <DiscoveryHealthPanel health={HEALTH_HEALTHY_SAMPLE} loading={false} error={null} />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Quarantined (repeated connect failures)
        </div>
        <DiscoveryHealthPanel health={HEALTH_QUARANTINED_SAMPLE} loading={false} error={null} />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          No discovery history yet
        </div>
        <DiscoveryHealthPanel health={HEALTH_EMPTY_SAMPLE} loading={false} error={null} />
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            ToolLatencyPanel (V2-MCP-31.2)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            How fast and how reliable is each tool? From the <code>tools</code> block of{' '}
            <code>insight/reliability</code>: an <strong>error-rate</strong> headline over the
            window, a <code>BarSeries</code> <strong>latency distribution</strong>, and a{' '}
            <strong>slowest</strong> (by p95) and <strong>flakiest</strong> (by error rate) tool
            ranking with each tool&apos;s p50/p95/p99. Has populated and empty (never-tested) states.
          </p>
        </div>
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Populated (a fast tool and a slow, flaky one)
        </div>
        <ToolLatencyPanel reliability={TOOLS_POPULATED_SAMPLE} loading={false} error={null} />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          No tool calls yet
        </div>
        <ToolLatencyPanel reliability={TOOLS_EMPTY_SAMPLE} loading={false} error={null} />
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            ScoreBreakdownPanel (V2-MCP-31.3)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Where did the quality grade come from? Decomposes the version&apos;s{' '}
            <code>mcp_version_scores.report</code> into a <strong>score reconstruction</strong>{' '}
            headline (grade gauge + the points the findings deducted, replayed from the scorer&apos;s
            model), <strong>points lost by rule group</strong> (a severity-tinted bar per category),
            a <code>BarSeries</code> <strong>findings-by-severity</strong> distribution, and a
            drill-down list of the findings — each linking to the capability it flags. Complements the
            Lint &amp; Score tab. Has populated and clean (no findings) states.
          </p>
        </div>
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Populated (a C grade across five rule groups)
        </div>
        <ScoreBreakdownPanel report={REPORT_POPULATED_SAMPLE} loading={false} error={null} />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Clean (full marks, no findings)
        </div>
        <ScoreBreakdownPanel report={REPORT_CLEAN_SAMPLE} loading={false} error={null} />
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            TrustProfilePanel (V2-MCP-31.4)
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            The capstone of the Insight tab&apos;s <em>Reliability &amp; trust</em> section: from{' '}
            <code>insight/trust</code> it collapses the scattered signals into one five-axis{' '}
            <code>Radar</code> — <strong>quality</strong>, <strong>safety</strong>,{' '}
            <strong>documentation</strong>, <strong>stability</strong>, and{' '}
            <strong>responsiveness</strong> — with an overall composite headline, a per-axis
            breakdown (each axis&apos;s <strong>methodology on hover</strong>), and unmeasured axes
            shown as explicit <strong>gaps</strong> rather than zeros. An explicitly heuristic
            composite, not an official rating. Has populated (with gaps) and not-enough-signal states.
          </p>
        </div>
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Populated (three axes scored, two gaps)
        </div>
        <TrustProfilePanel profile={TRUST_POPULATED_SAMPLE} loading={false} error={null} />
        <div className="text-xs font-medium uppercase tracking-wider text-gray-400">
          Nothing measured yet
        </div>
        <TrustProfilePanel profile={TRUST_EMPTY_SAMPLE} loading={false} error={null} />
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">JsonViewer</h2>
        <p className="mb-4 mt-1 text-sm text-gray-500 dark:text-gray-400">
          The read-only, monaco-backed code block for capability schemas &amp; catalog models —
          theme-aware, foldable, with one-click copy. Format-neutral via a <code>language</code> prop
          (defaults to JSON). Lives in <code>ui/code</code> (MFI-28.7).
        </p>
        <JsonViewer
          label="Input schema"
          value={JSON.stringify(
            {
              type: 'object',
              properties: {
                query: { type: 'string', description: 'Free-text search query.' },
                limit: { type: 'integer', minimum: 1, maximum: 100, default: 10 },
              },
              required: ['query'],
            },
            null,
            2,
          )}
        />
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">JsonDiffViewer</h2>
        <p className="mb-4 mt-1 text-sm text-gray-500 dark:text-gray-400">
          The read-only, monaco-backed split/unified diff for two revisions of a document — auto-sizing,
          theme-aware, collapsing long unchanged regions. Format-neutral via a <code>language</code> prop.
          Lives in <code>ui/code</code> (MFI-28.7).
        </p>
        <div className="w-full">
          <JsonDiffViewer
            mode="split"
            original={JSON.stringify(
              { name: 'search', limit: 10, sort: 'relevance' },
              null,
              2,
            )}
            modified={JSON.stringify(
              { name: 'search', limit: 25, sort: 'recency', highlight: true },
              null,
              2,
            )}
          />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Disclosure</h2>
        <p className="mb-4 mt-1 text-sm text-gray-500 dark:text-gray-400">
          A lazy-mounting collapsible wrapper for the (heavy) code viewers: its children mount only on
          first expand, so a long list of sections doesn&apos;t pay the editors&apos; cost up front.
          Lives in <code>ui/code</code> (MFI-28.7).
        </p>
        <div className="w-full space-y-2">
          <Disclosure label="Output schema" meta="6 lines">
            <JsonViewer
              className="rounded-none border-0"
              value={JSON.stringify(
                { type: 'array', items: { $ref: '#/components/schemas/Result' } },
                null,
                2,
              )}
            />
          </Disclosure>
        </div>
      </section>

      <Section title="FindingSeverity" description="The shared MUST / SHOULD / Advisory chip for the lint tab and inline hints.">
        <FindingSeverity tier="must" />
        <FindingSeverity tier="should" />
        <FindingSeverity tier="advisory" />
        <FindingSeverity severity="error" count={3} />
        <FindingSeverity severity="warning" count={5} />
      </Section>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">DetailTabs</h2>
        <p className="mb-4 mt-1 text-sm text-gray-500 dark:text-gray-400">
          The underline detail-tab shell. The canonical set lives in MCP_DETAIL_TABS.
        </p>
        <DetailTabs defaultValue="overview">
          <DetailTabsList items={MCP_DETAIL_TABS} />
          {MCP_DETAIL_TABS.map((tab) => (
            <DetailTabsContent key={tab.value} value={tab.value}>
              <p className="text-sm text-gray-600 dark:text-gray-300">
                {tab.label} panel content goes here.
              </p>
            </DetailTabsContent>
          ))}
        </DetailTabs>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Chart kit (V2-MCP-28.3)</h2>
        <p className="mb-4 mt-1 text-sm text-gray-500 dark:text-gray-400">
          The token-driven SVG primitives every insight panel reuses. Consumers pass domain data;
          each chart resolves color from Tailwind tokens (no hex literals), is accessible
          (<code>role=&quot;img&quot;</code> + hidden data table), responsive (viewBox), and renders an
          empty state — never a crash — for empty data. Toggle the theme to verify light + dark.
        </p>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-200">Sparkline</h3>
            <div className="flex flex-wrap items-center gap-4">
              <Sparkline data={[62, 65, 61, 70, 74, 73, 80, 86]} />
              <Sparkline data={[80, 74, 60, 52, 40, 38, 30]} tone="red" />
              <Sparkline data={[50]} tone="emerald" />
              <Sparkline data={[]} />
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-200">TrendLine</h3>
            <p className="mb-2 text-xs text-gray-500 dark:text-gray-400">
              A gapped line/area: a <code>null</code> entry breaks the line (a hollow tick), and
              optional markers pin an index. Left → a score trend with an unscored gap and a
              breaking-change marker; right → an empty state.
            </p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <TrendLine
                data={[62, 74, null, 80, 91]}
                tone="emerald"
                domainMax={100}
                markers={[3]}
                title="Quality score with a gap and a breaking-change marker"
              />
              <TrendLine data={[]} title="Empty trend" />
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-200">Gauge</h3>
            <div className="flex flex-wrap items-end gap-4">
              <Gauge value={94} />
              <Gauge value={61} />
              <Gauge value={18} />
              <Gauge value={420} min={0} max={1000} tone="blue" centerLabel="420ms" />
              <Gauge value={Number.NaN} />
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-200">BarSeries</h3>
            <BarSeries
              data={[
                { label: 'tools', value: 18 },
                { label: 'resources', value: 7 },
                { label: 'prompts', value: 3 },
                { label: 'destructive', value: 2, tone: 'red' },
              ]}
            />
          </div>

          <div>
            <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-200">Donut</h3>
            <div className="flex flex-wrap items-center gap-4">
              <Donut
                segments={[
                  { label: 'streamable_http', value: 12 },
                  { label: 'http+sse', value: 5 },
                  { label: 'stdio', value: 3 },
                ]}
                centerLabel="20"
              />
              <Donut segments={[]} />
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-200">StackedTimeline</h3>
            <StackedTimeline
              series={[
                { key: 'added', label: 'Added', tone: 'emerald' },
                { key: 'changed', label: 'Changed', tone: 'amber' },
                { key: 'removed', label: 'Removed', tone: 'red' },
              ]}
              periods={[
                { label: 'v1', values: { added: 8, changed: 0, removed: 0 } },
                { label: 'v2', values: { added: 3, changed: 4, removed: 1 } },
                { label: 'v3', values: { added: 2, changed: 2, removed: 3 } },
                { label: 'v4', values: { added: 5, changed: 1, removed: 0 } },
              ]}
            />
            <p className="mb-1 mt-3 text-xs text-gray-500 dark:text-gray-400">
              Interactive (<code>onSelectPeriod</code>) — each column is a keyboard-focusable button.
            </p>
            <StackedTimeline
              series={[
                { key: 'added', label: 'Added', tone: 'emerald' },
                { key: 'changed', label: 'Changed', tone: 'amber' },
                { key: 'removed', label: 'Removed', tone: 'red' },
              ]}
              periods={[
                { label: 'v1', values: { added: 8, changed: 0, removed: 0 } },
                { label: 'v2', values: { added: 0, changed: 0, removed: 0 } },
                { label: 'v3', values: { added: 2, changed: 4, removed: 3 } },
              ]}
              activeIndex={2}
              onSelectPeriod={() => {}}
              periodActionLabel={(p) => `Open ${p.label}`}
            />
          </div>

          <div>
            <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-200">Radar</h3>
            <Radar
              axes={[
                { label: 'Docs', value: 82 },
                { label: 'Annotations', value: 60 },
                { label: 'Output schemas', value: 45 },
                { label: 'Safety', value: 90 },
                { label: 'Simplicity', value: 70 },
              ]}
              max={100}
            />
          </div>

          <div>
            <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-200">Heatmap</h3>
            <Heatmap
              matrix={[
                [0, 1, 3, 6, 2],
                [2, 4, 8, 5, 1],
                [1, 0, 2, 9, 4],
              ]}
              rowLabels={['search', 'create', 'delete']}
              colLabels={['v1', 'v2', 'v3', 'v4', 'v5']}
            />
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Empty / loading / error states</h2>
        <EmptyState
          variant="compact"
          icon={<Server className="h-8 w-8 text-white" aria-hidden />}
          title="No endpoints yet"
          description="Import an MCP server to populate your catalog."
        />
        <LoadingState message="Loading catalog…" minHeightClassName="min-h-[160px]" />
        <ErrorState
          variant="compact"
          description="Could not reach the catalog service."
          onRetry={() => undefined}
        />
      </section>
    </main>
  );
}
