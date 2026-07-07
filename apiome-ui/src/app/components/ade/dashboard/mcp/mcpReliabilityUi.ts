/**
 * MCP discovery health & availability — shared types & pure presentation helpers
 * (V2-MCP-31.1 / MCAT-17.1, #4641).
 *
 * The Insight tab's "Discovery health timeline" shows whether an MCP server is *reliable over time*:
 * a timeline of its recent discovery-job outcomes (ok / unreachable / auth_error / …), an
 * availability percentage over that window, and its backoff / quarantine state — served by
 * apiome-rest as the `health` block of `/api/mcp/endpoints/{id}/insight/reliability`. This module is
 * the *pure, React-free* client layer over that payload: the typed wire shape, a defensive parser,
 * and the projection that turns the event list into what the {@link StackedTimeline} primitive
 * renders (plus the per-code failure breakdown the panel lists). Keeping it free of React/JSX lets
 * it be unit-tested directly and keeps the panel component free of payload-shaping branches —
 * mirroring {@link mcpEvolutionSeriesFromPayload}.
 */

import type {
  ChartSeriesTone,
  StackPeriod,
  StackSeries,
} from '@/app/components/ui/mcp/charts';

// --- Wire types ------------------------------------------------------------------------------
// One-to-one with the apiome-rest `McpDiscoveryHealthOut` / `McpDiscoveryEventOut` models.

/** One discovery-job outcome on the health timeline. */
export interface McpDiscoveryEvent {
  job_id: string;
  /** Lifecycle state: `queued` / `running` / `completed` / `failed`. */
  state: string;
  /** What enqueued the job: `manual` / `sweep` / `registry`. */
  trigger: string;
  /** `ok` (completed), a specific discovery error code (failed), or `pending` (in flight). */
  outcome: string;
  /** The raw discovery failure classification, or `null` for a non-failed job. */
  error_code: string | null;
  /** When the job was enqueued (ISO 8601), the axis is ordered by. */
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  /** Wall-clock run duration in ms, or `null` when the job never both started and finished. */
  duration_ms: number | null;
}

/** An endpoint's discovery health over a recent window: the outcome timeline + availability + state. */
export interface McpDiscoveryHealth {
  /** Recent per-job outcomes, newest-first (as the REST API returns them), capped at `window`. */
  timeline: McpDiscoveryEvent[];
  window: number;
  event_count: number;
  ok_count: number;
  failed_count: number;
  pending_count: number;
  terminal_count: number;
  /** `ok / (ok + failed)` over terminal jobs in the window as a 0–100 %, or `null` when none are terminal. */
  availability_pct: number | null;
  /** True when the window filled, so older jobs may exist beyond it. */
  truncated: boolean;
  /** True when the endpoint tripped the consecutive-failure threshold and is auto-excluded from the sweep. */
  quarantined: boolean;
  quarantined_at: string | null;
  quarantine_reason: string | null;
  /** Current back-to-back failure streak (drives backoff and the quarantine threshold). */
  consecutive_failures: number;
  /** Backoff anchor: the sweep holds off re-discovery until this time, or `null` when not backing off. */
  next_discovery_after: string | null;
  /** The most recent attempt's raw outcome status, or `null` before any discovery. */
  last_status: string | null;
  last_discovered_at: string | null;
}

// --- Defensive coercion ----------------------------------------------------------------------

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asInt(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : 0;
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** Parse one timeline event defensively, or `null` when it carries no resolvable job id. */
function eventFromPayload(raw: unknown): McpDiscoveryEvent | null {
  const r = (raw ?? {}) as Record<string, unknown>;
  const jobId = asString(r.job_id);
  if (!jobId) return null;
  return {
    job_id: jobId,
    state: asString(r.state) ?? 'unknown',
    trigger: asString(r.trigger) ?? 'unknown',
    outcome: asString(r.outcome) ?? 'pending',
    error_code: asString(r.error_code),
    created_at: asString(r.created_at),
    started_at: asString(r.started_at),
    finished_at: asString(r.finished_at),
    duration_ms: asNumber(r.duration_ms),
  };
}

/**
 * Parse the `health` block of an `insight/reliability` response into a {@link McpDiscoveryHealth}, or
 * `null` when the block is absent/malformed (the panel then shows its empty state, never a crash).
 * Every tally is re-derived from the parsed events rather than trusted from the wire, so the counts
 * the panel shows can never disagree with the timeline it renders.
 */
export function mcpReliabilityHealthFromPayload(data: unknown): McpDiscoveryHealth | null {
  const payload = (data ?? {}) as Record<string, unknown>;
  const raw = payload.health;
  if (!raw || typeof raw !== 'object') return null;
  const h = raw as Record<string, unknown>;

  const timeline = (Array.isArray(h.timeline) ? h.timeline : [])
    .map(eventFromPayload)
    .filter((e): e is McpDiscoveryEvent => e !== null);

  // Re-derive the tallies from the events so they always match what is drawn.
  let ok = 0;
  let failed = 0;
  let pending = 0;
  for (const event of timeline) {
    const kind = mcpDiscoveryOutcomeKind(event.outcome);
    if (kind === 'ok') ok += 1;
    else if (kind === 'pending') pending += 1;
    else failed += 1;
  }
  const terminal = ok + failed;
  const availability = terminal > 0 ? Math.round((ok / terminal) * 1000) / 10 : null;

  const window = asInt(h.window) || timeline.length;
  return {
    timeline,
    window,
    event_count: timeline.length,
    ok_count: ok,
    failed_count: failed,
    pending_count: pending,
    terminal_count: terminal,
    availability_pct: availability,
    truncated: h.truncated === true,
    quarantined: h.quarantined === true,
    quarantined_at: asString(h.quarantined_at),
    quarantine_reason: asString(h.quarantine_reason),
    consecutive_failures: asInt(h.consecutive_failures),
    next_discovery_after: asString(h.next_discovery_after),
    last_status: asString(h.last_status),
    last_discovered_at: asString(h.last_discovered_at),
  };
}

// --- Outcome classification ------------------------------------------------------------------

/** The three timeline bands an outcome collapses to (and the availability categories). */
export type McpOutcomeKind = 'ok' | 'failed' | 'pending';

/** Human-readable labels for the discovery outcomes the timeline surfaces, keyed by wire code. */
const OUTCOME_LABELS: Record<string, string> = {
  ok: 'OK',
  pending: 'Pending',
  failed: 'Failed',
  connect_timeout: 'Connect timeout',
  timeout: 'Timeout',
  connect_error: 'Unreachable',
  tls_error: 'TLS error',
  auth_required: 'Auth error',
  rate_limited: 'Rate limited',
  session_expired: 'Session expired',
  http_status: 'HTTP error',
  jsonrpc_error: 'JSON-RPC error',
  version_mismatch: 'Version mismatch',
  protocol_error: 'Protocol error',
  partial_page: 'Partial surface',
  ssrf_blocked: 'Blocked (SSRF)',
  budget_exceeded: 'Budget exceeded',
  unknown: 'Unknown error',
};

/** Collapse a wire outcome into its timeline band: `ok`, `pending` (in flight), or `failed`. */
export function mcpDiscoveryOutcomeKind(outcome: string): McpOutcomeKind {
  if (outcome === 'ok') return 'ok';
  if (outcome === 'pending') return 'pending';
  return 'failed';
}

/** A human label for a discovery outcome code — a friendly name, or a title-cased fallback. */
export function mcpDiscoveryOutcomeLabel(outcome: string): string {
  const known = OUTCOME_LABELS[outcome];
  if (known) return known;
  // Unknown/new code: title-case the snake_case value so it is still readable.
  return outcome
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

// --- Timeline projection ---------------------------------------------------------------------

/** The three outcome bands, pinned to the health colour language (healthy / failing / in-flight). */
export const MCP_HEALTH_SERIES: readonly StackSeries[] = [
  { key: 'ok', label: 'OK', tone: 'green' satisfies ChartSeriesTone },
  { key: 'failed', label: 'Failed', tone: 'red' satisfies ChartSeriesTone },
  { key: 'pending', label: 'Pending', tone: 'neutral' satisfies ChartSeriesTone },
];

/** One specific failure code and how many times it occurred across the window. */
export interface McpFailureTally {
  code: string;
  label: string;
  count: number;
}

/** The health timeline projected for the {@link StackedTimeline}, plus the panel's derived metadata. */
export interface McpDiscoveryHealthTimeline {
  /** The stacked bands (ok / failed / pending), in draw order. */
  series: readonly StackSeries[];
  /** One column per job, oldest→newest (the wire is newest-first, so this is the reversed order). */
  periods: StackPeriod[];
  /** Parallel to `periods`: the source event for each column, for tooltips / labels. */
  events: McpDiscoveryEvent[];
  /** Per-code failure breakdown across the window, most frequent first. */
  failures: McpFailureTally[];
  /** True when there is at least one event to plot. */
  hasEvents: boolean;
}

/** A compact, locale-free timestamp label (`YYYY-MM-DD HH:MM`) for an axis/tooltip; `—` when absent. */
export function mcpDiscoveryEventTime(iso: string | null): string {
  if (!iso) return '—';
  // Trim the ISO string to minute precision without a locale-dependent Date format (test-stable).
  const trimmed = iso.slice(0, 16).replace('T', ' ');
  return trimmed.length >= 16 ? trimmed : iso;
}

/** The accessible label / tooltip for one timeline column: its outcome, trigger, and time. */
export function mcpDiscoveryEventLabel(event: McpDiscoveryEvent): string {
  const outcome = mcpDiscoveryOutcomeLabel(event.outcome);
  const when = mcpDiscoveryEventTime(event.created_at);
  return `${outcome} · ${event.trigger} · ${when}`;
}

/**
 * Project a parsed {@link McpDiscoveryHealth} onto the timeline shape. Every job becomes one column;
 * the wire is newest-first, so the columns are reversed to read oldest→newest like the other Insight
 * timelines. Each column carries a single unit in its outcome band (`ok` / `failed` / `pending`), so
 * the {@link StackedTimeline} renders a uniform-height status strip coloured by outcome. Failed
 * events are also tallied by their specific error code (most frequent first) for the panel's
 * breakdown chips.
 */
export function mcpDiscoveryHealthTimeline(
  health: McpDiscoveryHealth,
): McpDiscoveryHealthTimeline {
  // Oldest→newest for the axis (the payload is newest-first).
  const ordered = [...health.timeline].reverse();
  const periods: StackPeriod[] = [];
  const failureCounts = new Map<string, number>();

  ordered.forEach((event) => {
    const kind = mcpDiscoveryOutcomeKind(event.outcome);
    periods.push({
      label: mcpDiscoveryEventTime(event.created_at),
      values: { ok: 0, failed: 0, pending: 0, [kind]: 1 },
    });
    if (kind === 'failed') {
      const code = event.outcome || 'failed';
      failureCounts.set(code, (failureCounts.get(code) ?? 0) + 1);
    }
  });

  const failures: McpFailureTally[] = Array.from(failureCounts.entries())
    .map(([code, count]) => ({ code, label: mcpDiscoveryOutcomeLabel(code), count }))
    // Most frequent first; ties broken alphabetically by label for a stable order.
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));

  return {
    series: MCP_HEALTH_SERIES,
    periods,
    events: ordered,
    failures,
    hasEvents: ordered.length > 0,
  };
}

/** The availability display tone: healthy (≥99%), degraded (≥90%), or poor (<90% / unknown). */
export function mcpAvailabilityKind(pct: number | null): 'healthy' | 'degraded' | 'poor' | 'unknown' {
  if (pct === null) return 'unknown';
  if (pct >= 99) return 'healthy';
  if (pct >= 90) return 'degraded';
  return 'poor';
}

// --- Per-tool latency & error-rate (V2-MCP-31.2 / MCAT-17.2) ----------------------------------
// One-to-one with the apiome-rest `McpToolInvocationReliabilityOut` block on `insight/reliability`.

/** Count / avg / min / max / p50 / p95 / p99 over a millisecond latency sample. */
export interface McpLatencyStats {
  count: number;
  avg_ms: number | null;
  min_ms: number | null;
  max_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
}

/** One tool's reliability over the window: call/error tallies, error rate, and latency stats. */
export interface McpToolLatency {
  tool_name: string;
  call_count: number;
  error_count: number;
  success_count: number;
  /** `error_count / call_count` as a 0–1 fraction. */
  error_rate: number;
  latency: McpLatencyStats;
}

/** One bar of the latency distribution: a labelled range and how many calls fell in it. */
export interface McpLatencyBucket {
  label: string;
  /** Exclusive upper bound of the range in ms, or `null` for the open-ended top bucket. */
  upper_ms: number | null;
  count: number;
}

/** An endpoint's per-tool reliability over a recent window: the breakdown, totals, and distribution. */
export interface McpToolReliability {
  /** Per-tool breakdown, busiest first (as the REST API returns them). */
  tools: McpToolLatency[];
  tool_count: number;
  /** Endpoint-wide totals across every tool call in the window. */
  call_count: number;
  error_count: number;
  success_count: number;
  error_rate: number;
  /** Histogram of every tool call's latency, for the distribution chart. */
  latency_distribution: McpLatencyBucket[];
  /** The trailing window (in days) the rows were aggregated over. */
  window_days: number;
}

/** Parse a latency-stats sub-object defensively (all statistics coerce to a number or `null`). */
function latencyStatsFromPayload(raw: unknown): McpLatencyStats {
  const r = (raw ?? {}) as Record<string, unknown>;
  return {
    count: asInt(r.count),
    avg_ms: asNumber(r.avg_ms),
    min_ms: asNumber(r.min_ms),
    max_ms: asNumber(r.max_ms),
    p50_ms: asNumber(r.p50_ms),
    p95_ms: asNumber(r.p95_ms),
    p99_ms: asNumber(r.p99_ms),
  };
}

/** Parse one per-tool row, or `null` when it carries no resolvable tool name. */
function toolLatencyFromPayload(raw: unknown): McpToolLatency | null {
  const r = (raw ?? {}) as Record<string, unknown>;
  const name = asString(r.tool_name);
  if (!name) return null;
  const callCount = asInt(r.call_count);
  const errorCount = asInt(r.error_count);
  return {
    tool_name: name,
    call_count: callCount,
    error_count: errorCount,
    success_count: asInt(r.success_count),
    // Re-derive the rate from the tallies so it can never disagree with the counts shown.
    error_rate: callCount > 0 ? errorCount / callCount : 0,
    latency: latencyStatsFromPayload(r.latency),
  };
}

/** Parse one distribution bucket, or `null` when it has no label. */
function latencyBucketFromPayload(raw: unknown): McpLatencyBucket | null {
  const r = (raw ?? {}) as Record<string, unknown>;
  const label = asString(r.label);
  if (!label) return null;
  return { label, upper_ms: asNumber(r.upper_ms), count: asInt(r.count) };
}

/**
 * Parse the `tools` block of an `insight/reliability` response into a {@link McpToolReliability}, or
 * `null` when the block is absent/malformed (the panel then shows its empty state, never a crash).
 * The endpoint-wide totals are re-derived from the parsed per-tool rows so they always agree with the
 * breakdown the panel renders.
 */
export function mcpToolReliabilityFromPayload(data: unknown): McpToolReliability | null {
  const payload = (data ?? {}) as Record<string, unknown>;
  const raw = payload.tools;
  if (!raw || typeof raw !== 'object') return null;
  const t = raw as Record<string, unknown>;

  const tools = (Array.isArray(t.tools) ? t.tools : [])
    .map(toolLatencyFromPayload)
    .filter((tool): tool is McpToolLatency => tool !== null);

  const distribution = (Array.isArray(t.latency_distribution) ? t.latency_distribution : [])
    .map(latencyBucketFromPayload)
    .filter((bucket): bucket is McpLatencyBucket => bucket !== null);

  // Re-derive the totals from the per-tool rows so the headline can never disagree with the list.
  let calls = 0;
  let errors = 0;
  for (const tool of tools) {
    calls += tool.call_count;
    errors += tool.error_count;
  }
  return {
    tools,
    tool_count: tools.length,
    call_count: calls,
    error_count: errors,
    success_count: calls - errors,
    error_rate: calls > 0 ? errors / calls : 0,
    latency_distribution: distribution,
    window_days: asInt(t.window_days),
  };
}

/**
 * The "slowest tools" ranking: tools that recorded at least one latency, ordered by p95 descending
 * (ties broken by p50, then name), capped at `limit`. Tools whose calls never completed (no latency
 * sample) are excluded — there is nothing to rank them by.
 */
export function mcpSlowestTools(tools: readonly McpToolLatency[], limit = 5): McpToolLatency[] {
  return tools
    .filter((tool) => tool.latency.count > 0 && tool.latency.p95_ms !== null)
    .slice()
    .sort(
      (a, b) =>
        (b.latency.p95_ms ?? 0) - (a.latency.p95_ms ?? 0) ||
        (b.latency.p50_ms ?? 0) - (a.latency.p50_ms ?? 0) ||
        a.tool_name.localeCompare(b.tool_name),
    )
    .slice(0, limit);
}

/**
 * The "flakiest tools" ranking: tools that errored at least once, ordered by error rate descending
 * (ties broken by call count, then name), capped at `limit`. Tools that never errored are excluded —
 * the ranking is about where the failures are.
 */
export function mcpFlakiestTools(tools: readonly McpToolLatency[], limit = 5): McpToolLatency[] {
  return tools
    .filter((tool) => tool.error_count > 0)
    .slice()
    .sort(
      (a, b) =>
        b.error_rate - a.error_rate ||
        b.call_count - a.call_count ||
        a.tool_name.localeCompare(b.tool_name),
    )
    .slice(0, limit);
}

/** A tool's error-rate display tone: healthy (0%), watch (<10%), or poor (≥10%). */
export function mcpErrorRateKind(rate: number): 'healthy' | 'watch' | 'poor' {
  if (rate <= 0) return 'healthy';
  if (rate < 0.1) return 'watch';
  return 'poor';
}

/** Format a nullable millisecond figure for display: `—`, `840 ms`, or `1.24 s` at/above a second. */
export function mcpFormatMs(value: number | null): string {
  if (value === null) return '—';
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  // Sub-second: whole milliseconds read cleanly and match the integer latencies we store.
  return `${Math.round(value)} ms`;
}

/** Format a 0–1 error-rate fraction as a percentage string (`0%`, `12.5%`), trimming trailing zeros. */
export function mcpFormatErrorRate(rate: number): string {
  const pct = rate * 100;
  const rounded = Math.round(pct * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}%`;
}
