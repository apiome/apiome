/**
 * Agent access — the React-free model behind the Control Panel's MCP → Agent access screen
 * (AGX-3.4, #4540).
 *
 * Three apiome-rest surfaces meet on that screen:
 *
 * - **Toolsets** (AGX-1.2): Agent Access for one published version — which of its operations
 *   agents may call. Reads are exposed by default; each write operation is opt-in and needs an
 *   explicit confirmation (`confirmWriteOp: true`).
 * - **Agent keys** (AGX-3.1, 3.2): the credential an agent presents, bound to one toolset, limited
 *   to a tool allowlist, optionally expiring, with today's usage against the tier's caps.
 * - **Usage** (AGX-3.3 rollups): calls, errors and latency per day, per tool and per agent.
 *
 * Everything here is pure — payload parsing, validation, the shapes the charts draw — so it is
 * unit-tested directly and the components stay thin.
 */

import type { BarDatum } from '@/app/components/ui/mcp/charts';

// ---------------------------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------------------------

/** Where a toolset's calls go: the real API, or its mock. */
export type AgentToolsetTarget = 'prod' | 'mock';

/** One operation of a toolset's version, exposed (or not) as an MCP tool. */
export interface AgentTool {
  id: string;
  /** The operation key, e.g. `GET /pets/{id}`. */
  operation: string;
  /** The MCP tool name agents see. */
  toolName: string;
  /** Whether calling it can change data upstream. */
  writeOp: boolean;
  /** Whether agents may call it. */
  enabled: boolean;
  /** When a write op's exposure was confirmed, if it is enabled. */
  writeConfirmedAt: string | null;
  /** Who confirmed it. */
  writeConfirmedBy: string | null;
}

/** A toolset's settings and tool counts. */
export interface AgentToolset {
  id: string;
  versionId: string;
  projectId: string;
  versionLabel: string | null;
  /** A disabled toolset exposes no tools at all. */
  enabled: boolean;
  target: AgentToolsetTarget;
  toolCount: number;
  enabledToolCount: number;
  enabledWriteOpCount: number;
  createdAt: string | null;
}

/** A toolset with every tool row. */
export interface AgentToolsetDetail extends AgentToolset {
  tools: AgentTool[];
}

/** An agent key's lifecycle state, as apiome-rest computes it. */
export type AgentKeyStatus = 'active' | 'disabled' | 'expired' | 'revoked';

/** An agent key's metadata. The secret is never part of it. */
export interface AgentKey {
  id: string;
  name: string;
  description: string | null;
  keyPrefix: string;
  toolsetId: string;
  toolAllowlist: string[];
  status: AgentKeyStatus;
  expiresAt: string | null;
  revokedAt: string | null;
  lastUsedAt: string | null;
  createdAt: string | null;
}

/** Today's usage of one key against its tier's caps (`null` cap = unlimited). */
export interface AgentKeyUsage {
  keyId: string;
  licenseType: string | null;
  rpsCap: number | null;
  dailyCap: number | null;
  used: number;
  remaining: number | null;
  resetsAt: string | null;
}

/** Calls, errors and latency for one slice of the usage window. */
export interface AgentUsageMetrics {
  calls: number;
  errors: number;
  /** `errors / calls`, in `[0, 1]`. */
  errorRate: number;
  latencyAvgMs: number | null;
  /** Worst p95 among the rollup groups covered — an upper bound on the true p95. */
  latencyP95MaxMs: number | null;
}

/** One day of the usage window. */
export interface AgentUsageDay extends AgentUsageMetrics {
  day: string;
}

/** One tool's usage over the window. */
export interface AgentUsageTool extends AgentUsageMetrics {
  toolName: string;
}

/** One agent key's usage over the window. */
export interface AgentUsageAgent extends AgentUsageMetrics {
  keyId: string;
  name: string | null;
  keyPrefix: string | null;
  revoked: boolean;
}

/** The whole window, with errors broken down by outcome. */
export interface AgentUsageTotals extends AgentUsageMetrics {
  successCalls: number;
  upstreamErrors: number;
  validationFailures: number;
  quotaRejections: number;
  internalErrors: number;
}

/** A tenant's agent usage over a window of UTC days. */
export interface AgentUsage {
  startDay: string;
  endDay: string;
  days: number;
  totals: AgentUsageTotals;
  daily: AgentUsageDay[];
  tools: AgentUsageTool[];
  agents: AgentUsageAgent[];
}

/** A published version that a toolset can be created for. */
export interface PublishedVersionOption {
  /** The `versions.id` UUID. */
  id: string;
  /** The version label, e.g. `1.2.0`. */
  label: string;
  projectId: string;
  projectName: string;
}

/** The create-key form's state. */
export interface AgentKeyDraft {
  name: string;
  description: string;
  toolsetId: string;
  /** Tool names the key may call. */
  toolAllowlist: string[];
  /** Whole days until expiry, as typed; empty for no expiry. */
  expiresInDays: string;
}

// ---------------------------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------------------------

/** apiome-rest's refusal when a write op is enabled without `confirmWriteOp: true`. */
export const CODE_WRITE_OP_UNCONFIRMED = 'agent-toolset-write-op-unconfirmed';

/** The usage windows the range picker offers, in days. */
export const USAGE_RANGES: readonly { days: number; label: string }[] = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
];

/** The window the usage panel opens on. */
export const DEFAULT_USAGE_DAYS = 30;

/** How many tools / agents the bar charts draw; the tables beneath list every one. */
export const USAGE_TOP_N = 8;

/** Longest agent key name apiome-rest accepts (`api_keys.name VARCHAR(255)`). */
export const AGENT_KEY_NAME_MAX = 255;

/** Longest expiry the form accepts, in days (ten years). */
export const AGENT_KEY_EXPIRY_MAX_DAYS = 3650;

/** The empty create-key form. */
export const EMPTY_AGENT_KEY_DRAFT: AgentKeyDraft = {
  name: '',
  description: '',
  toolsetId: '',
  toolAllowlist: [],
  expiresInDays: '',
};

// ---------------------------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------------------------

/** A record view of an unknown value; `{}` for anything that is not an object. */
function rec(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** A string field, or `null`. */
function str(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/** A finite number field, or `fallback`. */
function num(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

/** A finite number field, or `null`. */
function numOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** An array field, or `[]`. */
function arr(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/**
 * Parse one tool row.
 *
 * @param value - The REST `AgentToolOut`.
 * @returns The tool.
 */
export function parseAgentTool(value: unknown): AgentTool {
  const r = rec(value);
  return {
    id: str(r.id) ?? '',
    operation: str(r.operation) ?? '',
    toolName: str(r.toolName) ?? '',
    writeOp: r.writeOp === true,
    enabled: r.enabled === true,
    writeConfirmedAt: str(r.writeConfirmedAt),
    writeConfirmedBy: str(r.writeConfirmedBy),
  };
}

/**
 * Parse a toolset (with its tools, when the payload has them).
 *
 * @param value - The REST `AgentToolsetOut` / `AgentToolsetDetail`.
 * @returns The toolset; `tools` is `[]` for a list entry.
 */
export function parseAgentToolset(value: unknown): AgentToolsetDetail {
  const r = rec(value);
  return {
    id: str(r.id) ?? '',
    versionId: str(r.versionId) ?? '',
    projectId: str(r.projectId) ?? '',
    versionLabel: str(r.versionLabel),
    enabled: r.enabled === true,
    target: r.target === 'mock' ? 'mock' : 'prod',
    toolCount: num(r.toolCount),
    enabledToolCount: num(r.enabledToolCount),
    enabledWriteOpCount: num(r.enabledWriteOpCount),
    createdAt: str(r.createdAt),
    tools: arr(r.tools).map(parseAgentTool),
  };
}

/**
 * Parse the toolset list reply.
 *
 * @param value - `{toolsets: [...]}`.
 * @returns The toolsets, in the order apiome-rest sent them (newest first).
 */
export function parseAgentToolsetList(value: unknown): AgentToolsetDetail[] {
  return arr(rec(value).toolsets).map(parseAgentToolset);
}

/** The statuses apiome-rest reports, for narrowing. */
const KEY_STATUSES: readonly AgentKeyStatus[] = ['active', 'disabled', 'expired', 'revoked'];

/**
 * Parse one agent key.
 *
 * @param value - The REST `AgentKeyOut`.
 * @returns The key's metadata. Any `secret` on the payload is deliberately not copied.
 */
export function parseAgentKey(value: unknown): AgentKey {
  const r = rec(value);
  const status = KEY_STATUSES.find((s) => s === r.status) ?? 'disabled';
  return {
    id: str(r.id) ?? '',
    name: str(r.name) ?? '',
    description: str(r.description),
    keyPrefix: str(r.keyPrefix) ?? '',
    toolsetId: str(r.toolsetId) ?? '',
    toolAllowlist: arr(r.toolAllowlist).filter((t): t is string => typeof t === 'string'),
    status,
    expiresAt: str(r.expiresAt),
    revokedAt: str(r.revokedAt),
    lastUsedAt: str(r.lastUsedAt),
    createdAt: str(r.createdAt),
  };
}

/**
 * Parse the agent key list reply.
 *
 * @param value - `{keys: [...]}`.
 * @returns The keys, newest first.
 */
export function parseAgentKeyList(value: unknown): AgentKey[] {
  return arr(rec(value).keys).map(parseAgentKey);
}

/**
 * Parse one key's usage-vs-caps reply.
 *
 * @param value - The REST `AgentKeyUsageOut`.
 * @returns The usage.
 */
export function parseAgentKeyUsage(value: unknown): AgentKeyUsage {
  const r = rec(value);
  const daily = rec(r.dailyCalls);
  return {
    keyId: str(r.keyId) ?? '',
    licenseType: str(r.licenseType),
    rpsCap: numOrNull(rec(r.rps).cap),
    dailyCap: numOrNull(daily.cap),
    used: num(daily.used),
    remaining: numOrNull(daily.remaining),
    resetsAt: str(daily.resetsAt),
  };
}

/** Parse the metrics every usage slice shares. */
function parseMetrics(r: Record<string, unknown>): AgentUsageMetrics {
  return {
    calls: num(r.calls),
    errors: num(r.errors),
    errorRate: num(r.errorRate),
    latencyAvgMs: numOrNull(r.latencyAvgMs),
    latencyP95MaxMs: numOrNull(r.latencyP95MaxMs),
  };
}

/**
 * Parse the usage rollup reply.
 *
 * @param value - The REST `AgentUsageOut`.
 * @returns The usage.
 */
export function parseAgentUsage(value: unknown): AgentUsage {
  const r = rec(value);
  const totals = rec(r.totals);
  return {
    startDay: str(r.startDay) ?? '',
    endDay: str(r.endDay) ?? '',
    days: num(r.days),
    totals: {
      ...parseMetrics(totals),
      successCalls: num(totals.successCalls),
      upstreamErrors: num(totals.upstreamErrors),
      validationFailures: num(totals.validationFailures),
      quotaRejections: num(totals.quotaRejections),
      internalErrors: num(totals.internalErrors),
    },
    daily: arr(r.daily).map((d) => ({ ...parseMetrics(rec(d)), day: str(rec(d).day) ?? '' })),
    tools: arr(r.tools).map((t) => ({
      ...parseMetrics(rec(t)),
      toolName: str(rec(t).toolName) ?? '',
    })),
    agents: arr(r.agents).map((a) => {
      const ar = rec(a);
      return {
        ...parseMetrics(ar),
        keyId: str(ar.keyId) ?? '',
        name: str(ar.name),
        keyPrefix: str(ar.keyPrefix),
        revoked: ar.revoked === true,
      };
    }),
  };
}

/**
 * Parse the published-versions server action's reply into picker options.
 *
 * @param value - `{success, versions: [{id, version_id, project_id, project_name}]}`.
 * @returns The versions, in the order given (newest published first).
 */
export function parsePublishedVersionOptions(value: unknown): PublishedVersionOption[] {
  return arr(rec(value).versions)
    .map((v) => {
      const r = rec(v);
      return {
        id: str(r.id) ?? '',
        label: str(r.version_id) ?? '',
        projectId: str(r.project_id) ?? '',
        projectName: str(r.project_name) ?? '',
      };
    })
    .filter((v) => v.id !== '');
}

// ---------------------------------------------------------------------------------------------
// Toolsets
// ---------------------------------------------------------------------------------------------

/**
 * Whether moving a tool's switch needs the explicit write-op confirmation first.
 *
 * Only **enabling a write operation** does (AGX-1.2 policy). Disabling anything, or enabling a
 * read, is immediate.
 *
 * @param tool - The tool.
 * @param next - Where the switch was moved to.
 * @returns `true` when the confirmation dialog must be shown.
 */
export function toolToggleNeedsConfirmation(tool: AgentTool, next: boolean): boolean {
  return next && tool.writeOp && !tool.enabled;
}

/**
 * The published versions that have no toolset yet — the choices for "Enable Agent Access".
 *
 * @param versions - The tenant's published versions.
 * @param toolsets - Its existing toolsets.
 * @returns The versions without one.
 */
export function versionsWithoutToolset(
  versions: readonly PublishedVersionOption[],
  toolsets: readonly AgentToolset[]
): PublishedVersionOption[] {
  const taken = new Set(toolsets.map((t) => t.versionId));
  return versions.filter((v) => !taken.has(v.id));
}

/**
 * A toolset's human name: its project and version.
 *
 * @param toolset - The toolset.
 * @param versions - The published versions, to find the project's name.
 * @returns e.g. `Pet Store · 1.2.0`; the version label alone when the project is unknown.
 */
export function toolsetLabel(
  toolset: Pick<AgentToolset, 'versionId' | 'versionLabel'>,
  versions: readonly PublishedVersionOption[]
): string {
  const version = versions.find((v) => v.id === toolset.versionId);
  const label = toolset.versionLabel ?? version?.label ?? 'Unknown version';
  return version?.projectName ? `${version.projectName} · ${label}` : label;
}

/**
 * Apply one tool's update to a toolset, recounting its enabled tools.
 *
 * @param toolset - The toolset as shown.
 * @param tool - The tool as apiome-rest returned it after the change.
 * @returns A new toolset with the tool replaced and the counts recomputed.
 */
export function withUpdatedTool(
  toolset: AgentToolsetDetail,
  tool: AgentTool
): AgentToolsetDetail {
  const tools = toolset.tools.map((t) => (t.id === tool.id ? tool : t));
  return {
    ...toolset,
    tools,
    enabledToolCount: tools.filter((t) => t.enabled).length,
    enabledWriteOpCount: tools.filter((t) => t.enabled && t.writeOp).length,
  };
}

// ---------------------------------------------------------------------------------------------
// Agent keys
// ---------------------------------------------------------------------------------------------

/** MCP tool names apiome-rest accepts in an allowlist. */
const TOOL_NAME_RE = /^[A-Za-z0-9_-]{1,64}$/;

/**
 * Parse the expiry field.
 *
 * @param raw - What was typed.
 * @returns The whole number of days, `null` for "no expiry", or `NaN` when it is not acceptable.
 */
export function parseExpiryDays(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (!/^\d+$/.test(trimmed)) return Number.NaN;
  const days = Number(trimmed);
  return days >= 1 && days <= AGENT_KEY_EXPIRY_MAX_DAYS ? days : Number.NaN;
}

/**
 * Check the create-key form.
 *
 * @param draft - The form's state.
 * @returns The first problem to show, or `null` when it can be submitted.
 */
export function validateAgentKeyDraft(draft: AgentKeyDraft): string | null {
  const name = draft.name.trim();
  if (!name) return 'Name is required.';
  if (name.length > AGENT_KEY_NAME_MAX) {
    return `Name must be at most ${AGENT_KEY_NAME_MAX} characters.`;
  }
  if (!draft.toolsetId) return 'Choose the toolset this key may use.';
  if (draft.toolAllowlist.length === 0) {
    return 'Allow at least one tool — a key with an empty allowlist can call nothing.';
  }
  if (draft.toolAllowlist.some((t) => !TOOL_NAME_RE.test(t))) {
    return 'The allowlist contains a name that is not an MCP tool name.';
  }
  if (Number.isNaN(parseExpiryDays(draft.expiresInDays) as number)) {
    return `Expiry must be a whole number of days between 1 and ${AGENT_KEY_EXPIRY_MAX_DAYS}, or empty.`;
  }
  return null;
}

/**
 * The create-key request body for a valid draft.
 *
 * @param draft - The form's state (already validated).
 * @param now - The moment expiry is counted from.
 * @returns `{name, description?, toolsetId, toolAllowlist, expiresAt?}`.
 */
export function agentKeyCreateBody(
  draft: AgentKeyDraft,
  now: Date
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    name: draft.name.trim(),
    toolsetId: draft.toolsetId,
    toolAllowlist: [...new Set(draft.toolAllowlist)].sort(),
  };
  const description = draft.description.trim();
  if (description) body.description = description;
  const days = parseExpiryDays(draft.expiresInDays);
  if (typeof days === 'number' && !Number.isNaN(days)) {
    body.expiresAt = new Date(now.getTime() + days * 86_400_000).toISOString();
  }
  return body;
}

/**
 * The tool names a key may be allowed: the toolset's enabled tools.
 *
 * @param toolset - The toolset, with its tools.
 * @returns The enabled tools' names, sorted.
 */
export function allowableToolNames(toolset: Pick<AgentToolsetDetail, 'tools'>): string[] {
  return toolset.tools
    .filter((t) => t.enabled)
    .map((t) => t.toolName)
    .sort();
}

/**
 * The entries of an allowlist that the toolset does not currently expose.
 *
 * They stay in the allowlist (the toolset may re-enable them), but the key cannot call them now.
 *
 * @param allowlist - The key's allowlist.
 * @param toolset - Its toolset, with tools.
 * @returns The names that are not enabled tools, sorted.
 */
export function inactiveAllowlistEntries(
  allowlist: readonly string[],
  toolset: Pick<AgentToolsetDetail, 'tools'>
): string[] {
  const enabled = new Set(allowableToolNames(toolset));
  return allowlist.filter((name) => !enabled.has(name)).sort();
}

/**
 * Whether two allowlists name different tools (order and duplicates ignored).
 *
 * @param a - One list.
 * @param b - The other.
 * @returns `true` when saving `b` over `a` would change something.
 */
export function allowlistChanged(a: readonly string[], b: readonly string[]): boolean {
  const left = new Set(a);
  const right = new Set(b);
  if (left.size !== right.size) return true;
  for (const name of left) if (!right.has(name)) return true;
  return false;
}

/**
 * Add or remove one name from a selection.
 *
 * @param selection - The current names.
 * @param name - The name toggled.
 * @param checked - Whether it is now selected.
 * @returns The new selection, sorted and without duplicates.
 */
export function toggleName(
  selection: readonly string[],
  name: string,
  checked: boolean
): string[] {
  const next = new Set(selection);
  if (checked) next.add(name);
  else next.delete(name);
  return [...next].sort();
}

/**
 * Whether a key can still be changed (allowlist edit, revoke).
 *
 * @param key - The key.
 * @returns `false` for a revoked key.
 */
export function agentKeyIsMutable(key: Pick<AgentKey, 'status'>): boolean {
  return key.status !== 'revoked';
}

/**
 * The daily-cap meter for a key, or `null` when the cap is unlimited.
 *
 * @param usage - The key's usage.
 * @returns `{value, max, valueText}` for `Meter`.
 */
export function dailyQuotaMeter(
  usage: AgentKeyUsage
): { value: number; max: number; valueText: string } | null {
  if (usage.dailyCap === null || usage.dailyCap <= 0) return null;
  return {
    value: Math.min(usage.used, usage.dailyCap),
    max: usage.dailyCap,
    valueText: `${formatCount(usage.used)} of ${formatCount(usage.dailyCap)} calls today`,
  };
}

/**
 * One line describing a key's caps.
 *
 * @param usage - The key's usage.
 * @returns e.g. `2 calls/s · 1,000 calls/day` or `Unlimited`.
 */
export function describeCaps(usage: AgentKeyUsage): string {
  const rps = usage.rpsCap === null ? 'no rate limit' : `${formatCount(usage.rpsCap)} calls/s`;
  const daily =
    usage.dailyCap === null ? 'no daily cap' : `${formatCount(usage.dailyCap)} calls/day`;
  if (usage.rpsCap === null && usage.dailyCap === null) return 'Unlimited';
  return `${rps} · ${daily}`;
}

// ---------------------------------------------------------------------------------------------
// Usage
// ---------------------------------------------------------------------------------------------

/**
 * Format a count for display.
 *
 * @param value - The number.
 * @returns It, grouped (`1,234`).
 */
export function formatCount(value: number): string {
  return value.toLocaleString('en-US');
}

/**
 * Format an error rate.
 *
 * @param rate - A fraction in `[0, 1]`.
 * @returns e.g. `4.2%`; `0%` for no errors.
 */
export function formatRate(rate: number): string {
  if (!Number.isFinite(rate) || rate <= 0) return '0%';
  const pct = rate * 100;
  return `${pct >= 10 ? Math.round(pct) : Math.round(pct * 10) / 10}%`;
}

/**
 * Format a latency.
 *
 * @param ms - Milliseconds, or `null`.
 * @returns e.g. `182 ms`, `1.4 s`, or `—` when there is none.
 */
export function formatLatency(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return '—';
  if (ms >= 1000) return `${Math.round(ms / 100) / 10} s`;
  return `${Math.round(ms)} ms`;
}

/**
 * Whether the window has no calls at all — the usage panel's empty state.
 *
 * @param usage - The usage.
 * @returns `true` when nothing was called.
 */
export function usageIsEmpty(usage: Pick<AgentUsage, 'totals'>): boolean {
  return usage.totals.calls <= 0;
}

/**
 * The per-day series the trend charts draw.
 *
 * A day without calls has no error rate and no latency: those are gaps (`null`), not zeros, so a
 * quiet day is never drawn as a perfect one.
 *
 * @param usage - The usage.
 * @returns `calls`, `errors`, `errorRatePct` and `latencyAvgMs`, one entry per day.
 */
export function usageDailySeries(usage: Pick<AgentUsage, 'daily'>): {
  calls: number[];
  errors: number[];
  errorRatePct: (number | null)[];
  latencyAvgMs: (number | null)[];
} {
  return {
    calls: usage.daily.map((d) => d.calls),
    errors: usage.daily.map((d) => d.errors),
    errorRatePct: usage.daily.map((d) =>
      d.calls > 0 ? Math.round(d.errorRate * 1000) / 10 : null
    ),
    latencyAvgMs: usage.daily.map((d) =>
      d.calls > 0 && d.latencyAvgMs !== null ? Math.round(d.latencyAvgMs) : null
    ),
  };
}

/**
 * The display name of an agent in the usage charts.
 *
 * @param agent - The agent's usage entry.
 * @returns Its name, else its prefix, else a short id; `(revoked)` appended when revoked.
 */
export function usageAgentLabel(agent: Pick<AgentUsageAgent, 'name' | 'keyPrefix' | 'keyId' | 'revoked'>): string {
  const base = agent.name ?? agent.keyPrefix ?? `key ${agent.keyId.slice(0, 8)}`;
  return agent.revoked ? `${base} (revoked)` : base;
}

/**
 * The bars of a "top N" chart.
 *
 * @param entries - Entries sorted most calls first (as apiome-rest sends them).
 * @param label - How to name an entry.
 * @param n - How many bars.
 * @returns At most `n` bars of calls.
 */
export function topBars<T extends AgentUsageMetrics>(
  entries: readonly T[],
  label: (entry: T) => string,
  n = USAGE_TOP_N
): BarDatum[] {
  return entries.slice(0, n).map((entry) => ({ label: label(entry), value: entry.calls }));
}

/**
 * A short label for a calendar day.
 *
 * @param day - `YYYY-MM-DD`.
 * @returns e.g. `Oct 6`; the input when it is not a date.
 */
export function formatDay(day: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return day;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}
