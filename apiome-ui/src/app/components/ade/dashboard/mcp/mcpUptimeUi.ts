/**
 * MCP endpoint uptime — the pure client layer behind the health badge (V2-MCP-27.3 / MCAT-13.3, #3713).
 *
 * The health sweep in apiome-rest probes each endpoint with the MCP `initialize` handshake every few
 * minutes; `GET /v1/mcp/{tenant}/endpoints/{id}/uptime` folds the last 24 hours of probes into a
 * summary. This module parses that payload defensively and turns the summary into what the endpoint
 * page's badge prints — the status word, the uptime figure, the median latency and a tooltip — so the
 * component only renders. Nothing here touches React or the network.
 */

import { mcpFormatMs } from './mcpReliabilityUi';

/** The summary status apiome-rest derives (`app.mcp_health.derive_uptime_status`). */
export type McpUptimeStatus = 'up' | 'degraded' | 'down' | 'unknown';

/** The `summary` block of the uptime payload. */
export interface McpUptimeSummary {
  status: McpUptimeStatus;
  windowHours: number;
  checks: number;
  up: number;
  down: number;
  /** Successful probes over all probes, 0–100; `null` with no probe in the window. */
  uptimePct: number | null;
  /** Median latency of the successful probes in ms; `null` when none succeeded. */
  latencyP50Ms: number | null;
  latencyP95Ms: number | null;
  /** ISO-8601 time of the latest probe; `null` with none. */
  lastCheckedAt: string | null;
  /** The latest probe's error code when it failed. */
  lastErrorCode: string | null;
}

const STATUSES: readonly McpUptimeStatus[] = ['up', 'degraded', 'down', 'unknown'];

/** Status word shown on the badge. */
const STATUS_LABEL: Record<McpUptimeStatus, string> = {
  up: 'Up',
  degraded: 'Degraded',
  down: 'Down',
  unknown: 'Uptime unknown',
};

/**
 * The shared status-vocabulary string each uptime status is drawn with (`ui/statusVocabulary`), so
 * the badge takes its colours from the same tokens as every other status pill.
 */
const STATUS_VOCABULARY: Record<McpUptimeStatus, string> = {
  up: 'healthy',
  degraded: 'degraded',
  down: 'down',
  unknown: 'unknown',
};

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asCount(value: unknown): number {
  const n = asNumber(value);
  return n !== null && n > 0 ? Math.floor(n) : 0;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

/**
 * Parse the uptime payload's `summary` block.
 *
 * @param data The JSON body of `/api/mcp/endpoints/{id}/uptime`.
 * @returns The summary, or `null` when the payload carries none. An unrecognised status reads `unknown`.
 */
export function mcpUptimeSummaryFromPayload(data: unknown): McpUptimeSummary | null {
  const payload = (data ?? {}) as Record<string, unknown>;
  const raw = payload.summary;
  if (!raw || typeof raw !== 'object') return null;
  const s = raw as Record<string, unknown>;
  const status = STATUSES.includes(s.status as McpUptimeStatus)
    ? (s.status as McpUptimeStatus)
    : 'unknown';
  return {
    status,
    windowHours: asCount(s.window_hours),
    checks: asCount(s.checks),
    up: asCount(s.up),
    down: asCount(s.down),
    uptimePct: asNumber(s.uptime_pct),
    latencyP50Ms: asNumber(s.latency_p50_ms),
    latencyP95Ms: asNumber(s.latency_p95_ms),
    lastCheckedAt: asString(s.last_checked_at),
    lastErrorCode: asString(s.last_error_code),
  };
}

/**
 * Render an uptime percentage compactly, rounding *down* to one decimal so a window with any failed
 * probe never reads `100%` (the same rule as the public SVG badge).
 */
export function mcpFormatUptimePct(pct: number | null): string {
  if (pct === null) return '';
  const floored = Math.floor(pct * 10) / 10;
  return floored >= 100 ? '100%' : `${floored.toFixed(1)}%`;
}

/** What the badge prints and how it is coloured. */
export interface McpUptimeBadge {
  /** The status-vocabulary string for `<Badge status>`. */
  vocabulary: string;
  /** The visible text, e.g. `Up · 99.9% · 120 ms`. */
  text: string;
  /** The tooltip / accessible description. */
  title: string;
}

/**
 * Build the badge for a summary. `null` (not loaded, or the read failed) and a summary with no
 * probes both read `Uptime unknown`.
 *
 * @param summary The parsed summary, or `null`.
 * @returns The badge's vocabulary string, visible text and tooltip.
 */
export function mcpUptimeBadge(summary: McpUptimeSummary | null): McpUptimeBadge {
  const status: McpUptimeStatus = summary?.status ?? 'unknown';
  const parts = [STATUS_LABEL[status]];
  if (summary && status !== 'unknown') {
    const pct = mcpFormatUptimePct(summary.uptimePct);
    if (pct) parts.push(pct);
    if (summary.latencyP50Ms !== null) parts.push(mcpFormatMs(summary.latencyP50Ms));
  }

  const hours = summary?.windowHours || 24;
  let title: string;
  if (!summary || summary.checks === 0) {
    title = `No reachability probes in the last ${hours} hours.`;
  } else {
    const probes = `${summary.up} of ${summary.checks} probes answered in the last ${hours} hours`;
    const latency =
      summary.latencyP50Ms !== null
        ? `; median ${mcpFormatMs(summary.latencyP50Ms)}, p95 ${mcpFormatMs(summary.latencyP95Ms)}`
        : '';
    const failure =
      status === 'down' && summary.lastErrorCode ? `. Last probe failed: ${summary.lastErrorCode}` : '';
    title = `${probes}${latency}${failure}.`;
  }
  return { vocabulary: STATUS_VOCABULARY[status], text: parts.join(' · '), title };
}
