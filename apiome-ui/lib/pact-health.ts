/**
 * Contract health rollup and verification analytics — PFX-6.3 (#6955): the shared model of the
 * **Health** pages, their `/api/pact/health*` proxies, and the health badge on the **Verification**
 * page.
 *
 * Everything here is pure: types mirroring apiome-rest (`app.pact_health`), the wording of states,
 * signals and windows, routes and proxy paths, the checks the proxies run on a query before anything
 * reaches REST (an unknown, repeated, empty or malformed parameter is a 400 naming it), and the
 * geometry of the trend charts.
 */

import { isPacticipantHandle } from '@lib/pact-pacticipants';

// --- types ----------------------------------------------------------------------------------------

/** A pair's fused state. */
export type HealthState = 'healthy' | 'degraded' | 'failing' | 'unknown';

/** One signal's status. */
export type SignalStatus = 'ok' | 'warn' | 'fail' | 'unknown';

/** A selectable window. */
export type HealthWindow = '7d' | '30d' | '90d';

/** A pair's (or a bucket's, or the workspace's) analytics. */
export interface PairMetrics {
  runs: number;
  passed: number;
  failed: number;
  /** 0 … 1, or null with no runs. */
  pass_rate: number | null;
  flips: number;
  /** 0 … 1, or null with fewer than two results. */
  flakiness: number | null;
  timed_runs: number;
  mean_duration_ms: number | null;
}

/** One fused signal. */
export interface HealthComponent {
  key: string;
  status: SignalStatus;
  code: string;
  summary: string;
}

/** One pair's health. */
export interface PairHealth {
  provider: string;
  provider_name: string;
  consumer: string;
  consumer_name: string;
  pact_version_sha: string;
  consumer_version: string;
  published_at: string | null;
  state: HealthState;
  components: HealthComponent[];
  metrics: PairMetrics;
  latest_success: boolean | null;
  latest_verified_at: string | null;
  republish_request_id: string | null;
}

/** Pairs per state. */
export interface HealthCounts {
  pairs: number;
  healthy: number;
  degraded: number;
  failing: number;
  unknown: number;
}

/** The workspace's health over a window. */
export interface HealthOverview {
  window: HealthWindow;
  since: string;
  until: string;
  bucket_days: number;
  generated_at: string;
  counts: HealthCounts;
  totals: PairMetrics;
  pairs: PairHealth[];
  truncated: boolean;
  omitted_pairs: number;
}

/** One bucket of a pair's trend. */
export interface TrendBucket {
  start: string;
  end: string;
  metrics: PairMetrics;
}

/** One pair's health and trend. */
export interface PairHealthDetail {
  window: HealthWindow;
  since: string;
  until: string;
  bucket_days: number;
  generated_at: string;
  pair: PairHealth;
  trend: TrendBucket[];
}

// --- wording ----------------------------------------------------------------------------------------

/** A badge tone. */
export type HealthVariant = 'ok' | 'warn' | 'danger' | 'neutral';

/** Every state, worst first (the order REST sorts by). */
export const HEALTH_STATES: readonly HealthState[] = ['failing', 'degraded', 'unknown', 'healthy'];

/** How each state reads. */
export const STATE_TEXT: Record<
  HealthState,
  { label: string; variant: HealthVariant; description: string }
> = {
  healthy: { label: 'Healthy', variant: 'ok', description: 'Every signal with evidence is fine.' },
  degraded: {
    label: 'Degraded',
    variant: 'warn',
    description: 'At least one signal warns; none fails.',
  },
  failing: { label: 'Failing', variant: 'danger', description: 'At least one signal fails.' },
  unknown: {
    label: 'Unknown',
    variant: 'neutral',
    description: 'No signal has evidence either way yet.',
  },
};

/**
 * How a state reads; an unknown value reads as **Unknown**.
 *
 * @param state - The state.
 * @returns The label, badge tone and description.
 */
export function healthStateText(state: string): {
  label: string;
  variant: HealthVariant;
  description: string;
} {
  return STATE_TEXT[state as HealthState] ?? STATE_TEXT.unknown;
}

/** How each signal status reads. */
export const STATUS_TEXT: Record<SignalStatus, { label: string; variant: HealthVariant }> = {
  ok: { label: 'OK', variant: 'ok' },
  warn: { label: 'Warning', variant: 'warn' },
  fail: { label: 'Failing', variant: 'danger' },
  unknown: { label: 'No evidence', variant: 'neutral' },
};

/**
 * How a signal status reads.
 *
 * @param status - The status.
 * @returns The label and tone.
 */
export function signalStatusText(status: string): { label: string; variant: HealthVariant } {
  return STATUS_TEXT[status as SignalStatus] ?? STATUS_TEXT.unknown;
}

/** Each signal's name, by key. */
export const SIGNAL_LABEL: Record<string, string> = {
  'latest-verdict': 'Latest verdict',
  'pass-rate': 'Pass rate',
  flakiness: 'Flakiness',
  overdue: 'Overdue',
  'republish-request': 'Re-publish request',
  webhooks: 'Webhooks',
};

/**
 * A signal's name; an unknown key reads as itself.
 *
 * @param key - The component key.
 * @returns The name.
 */
export function signalLabel(key: string): string {
  return SIGNAL_LABEL[key] ?? key;
}

/** Every window, in the order the picker lists them. */
export const HEALTH_WINDOWS: readonly HealthWindow[] = ['7d', '30d', '90d'];

/** The window used when none is chosen. */
export const DEFAULT_WINDOW: HealthWindow = '30d';

/** How each window reads. */
export const WINDOW_TEXT: Record<HealthWindow, string> = {
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
  '90d': 'Last 90 days',
};

/**
 * A window from the address; anything else reads as the default.
 *
 * @param value - The `?window=` value.
 * @returns The window.
 */
export function readWindow(value: string | null | undefined): HealthWindow {
  return (HEALTH_WINDOWS as readonly string[]).includes(value ?? '')
    ? (value as HealthWindow)
    : DEFAULT_WINDOW;
}

/**
 * A share as a whole percentage, or a dash.
 *
 * @param value - 0 … 1, or null.
 * @returns E.g. `96%`, or `—`.
 */
export function formatShare(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '—';
}

/**
 * A duration in milliseconds, or a dash.
 *
 * @param value - Milliseconds, or null.
 * @returns E.g. `850 ms`, `2.4 s`, `1.5 min`, or `—`.
 */
export function formatDuration(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '—';
  if (value < 1000) return `${Math.round(value)} ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(1)} s`;
  return `${(value / 60_000).toFixed(1)} min`;
}

// --- routes ------------------------------------------------------------------------------------------

/** The Health page. */
export const HEALTH_ROUTE = '/ade/dashboard/pacts/health';

/**
 * The Health page, optionally narrowed.
 *
 * @param filters - `window`, `state` and `provider`.
 * @returns The route (the default window is left out).
 */
export function healthRoute(
  filters: { window?: string | null; state?: string | null; provider?: string | null } = {},
) {
  const query = new URLSearchParams();
  if (filters.window && filters.window !== DEFAULT_WINDOW) query.set('window', filters.window);
  if (filters.state) query.set('state', filters.state);
  if (filters.provider) query.set('provider', filters.provider);
  const rendered = query.toString();
  return rendered ? `${HEALTH_ROUTE}?${rendered}` : HEALTH_ROUTE;
}

/**
 * One pair's health page.
 *
 * @param provider - The provider's handle.
 * @param consumer - The consumer's handle.
 * @param window - The window (the default is left out).
 * @returns The route.
 */
export function pairHealthRoute(
  provider: string,
  consumer: string,
  window?: string | null,
): string {
  const path = `${HEALTH_ROUTE}/${encodeURIComponent(provider)}/${encodeURIComponent(consumer)}`;
  return window && window !== DEFAULT_WINDOW ? `${path}?window=${window}` : path;
}

/** The REST path below `/v1/tenants/{slug}/` (no leading slash). */
export const HEALTH_PROXY_PATH = 'pact-health';

/**
 * The REST path of one pair's health.
 *
 * @param provider - The provider's handle (already checked).
 * @param consumer - The consumer's handle (already checked).
 * @returns The path.
 */
export function pairHealthProxyPath(provider: string, consumer: string): string {
  return `${HEALTH_PROXY_PATH}/providers/${encodeURIComponent(provider)}/consumers/${encodeURIComponent(consumer)}`;
}

// --- proxy checks -------------------------------------------------------------------------------------

/** The overview's parameters. */
export const OVERVIEW_PARAMETERS = ['window', 'provider', 'consumer', 'state'] as const;

/**
 * What is wrong with a query, or `null`.
 *
 * @param params - The browser's query string.
 * @param allowed - The parameters this read accepts.
 * @returns The 400's message, or `null`.
 */
export function healthQueryProblem(
  params: URLSearchParams,
  allowed: readonly string[] = OVERVIEW_PARAMETERS,
): string | null {
  for (const key of new Set(params.keys())) {
    if (!allowed.includes(key))
      return `Unsupported parameter ${key}: this read accepts ${allowed.join(', ')}.`;
    if (params.getAll(key).length > 1) return `The ${key} parameter is given more than once.`;
    const value = params.get(key) ?? '';
    if (!value) return `The ${key} parameter is empty.`;
    if (key === 'window' && !(HEALTH_WINDOWS as readonly string[]).includes(value)) {
      return `The window parameter must be one of ${HEALTH_WINDOWS.join(', ')}.`;
    }
    if (key === 'state' && !(HEALTH_STATES as readonly string[]).includes(value)) {
      return `The state parameter must be one of ${HEALTH_STATES.join(', ')}.`;
    }
    if ((key === 'provider' || key === 'consumer') && !isPacticipantHandle(value)) {
      return `The ${key} parameter is not a pacticipant handle.`;
    }
  }
  return null;
}

/**
 * The REST path of a checked read, with the parameters in a fixed order.
 *
 * @param path - The REST path.
 * @param params - The checked query.
 * @param allowed - The parameters to pass on.
 * @returns The path with its query.
 */
export function healthProxyPath(
  path: string,
  params: URLSearchParams,
  allowed: readonly string[],
): string {
  const query = new URLSearchParams();
  for (const key of allowed) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  const rendered = query.toString();
  return rendered ? `${path}?${rendered}` : path;
}

// --- reading -------------------------------------------------------------------------------------------

/**
 * Each consumer's health of one provider, by consumer handle (for the Verification page).
 *
 * @param overview - The overview narrowed to the provider.
 * @returns The pairs by consumer.
 */
export function healthByConsumer(
  overview: HealthOverview | null | undefined,
): Record<string, PairHealth> {
  const byConsumer: Record<string, PairHealth> = {};
  for (const pair of overview?.pairs ?? []) byConsumer[pair.consumer] = pair;
  return byConsumer;
}

/**
 * The components that are not fine, worst first — what a pair's row says next to its state.
 *
 * @param pair - The pair.
 * @returns The failing, then warning components.
 */
export function concerns(pair: Pick<PairHealth, 'components'>): HealthComponent[] {
  const rank: Record<string, number> = { fail: 0, warn: 1 };
  return pair.components
    .filter((component) => component.status === 'fail' || component.status === 'warn')
    .sort((a, b) => rank[a.status] - rank[b.status]);
}

// --- trend chart geometry -----------------------------------------------------------------------------

/** The chart's drawing box, in SVG user units (it scales to its container). */
export const CHART = { width: 640, height: 160, padX: 36, padY: 14 } as const;

/** One drawn point: x and y in the drawing box, and the bucket it stands for. */
export interface ChartPoint {
  x: number;
  y: number;
  index: number;
  value: number;
}

/**
 * Where each bucket's value lands in the chart; buckets with no value are left out, so the line
 * has gaps rather than inventing zeros.
 *
 * @param values - One value (or null) per bucket, oldest first.
 * @param max - The value at the top of the chart (at least 1 is used).
 * @returns The points.
 */
export function chartPoints(values: Array<number | null>, max: number): ChartPoint[] {
  const top = max > 0 ? max : 1;
  const span = CHART.width - CHART.padX * 2;
  const height = CHART.height - CHART.padY * 2;
  const step = values.length > 1 ? span / (values.length - 1) : 0;
  const points: ChartPoint[] = [];
  values.forEach((value, index) => {
    if (value === null || !Number.isFinite(value)) return;
    const clamped = Math.min(Math.max(value, 0), top);
    points.push({
      x: round(CHART.padX + (values.length > 1 ? step * index : span / 2)),
      y: round(CHART.padY + height - (clamped / top) * height),
      index,
      value,
    });
  });
  return points;
}

/**
 * The SVG path of the line through consecutive points; a gap (a bucket with no value) starts a new
 * segment.
 *
 * @param points - The points, by bucket index.
 * @returns The `d` attribute (empty with no points).
 */
export function chartPath(points: ChartPoint[]): string {
  return points
    .map((point, position) => {
      const joined = position > 0 && points[position - 1].index === point.index - 1;
      return `${joined ? 'L' : 'M'}${point.x} ${point.y}`;
    })
    .join(' ');
}

/** Two decimals are plenty for SVG coordinates and keep snapshots stable. */
function round(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * A bucket's day as a label (buckets start at midnight UTC).
 *
 * @param iso - The bucket's start.
 * @returns E.g. `2026-11-26`, or `—`.
 */
export function formatDay(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '—' : date.toISOString().slice(0, 10);
}
