/**
 * Export history — the pure half (MFX-46.1, #4379).
 *
 * The **History** tab of Export studio answers "who exported what, where, with how much loss?" for the
 * whole workspace, from the export run ledger (`GET /v1/export/{tenant}/runs`). This module holds what the
 * screen computes without React:
 *
 *  - the run shapes (mirrors of REST `ExportRunSummary` / `ExportRunDetail`);
 *  - the filters and their query string ({@link historyQuery}), validated so a hand-edited value never
 *    reaches the server;
 *  - the words and tones of each verdict, so a verdict is never colour alone;
 *  - {@link deliverySummary}: each channel's deliveries in one line;
 *  - {@link rerunHref}: the Export studio link that re-runs a run with its source, version, target and
 *    options pre-filled (the MFX-41.3 re-run mechanism).
 */

import { exportStudioHref } from '../../dashboard/export/exportStudioLink';

// ---------------------------------------------------------------------------
// Shapes
// ---------------------------------------------------------------------------

/** One delivery of a run (mirror of REST `ExportRunDelivery`). */
export interface ExportRunDelivery {
  channel: 'git' | 'webhook' | 'object-storage' | string;
  status: string;
  outcome: 'delivered' | 'failed' | 'in_progress' | string;
  destination?: string | null;
  error_code?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

/** One run of the history (mirror of REST `ExportRunSummary`). */
export interface ExportRunSummary {
  job_id: string;
  artifact_id: string;
  artifact_name?: string | null;
  version_record_id?: string | null;
  version_label?: string | null;
  target: string;
  actor_id?: string | null;
  actor_label: string;
  state: 'completed' | 'failed' | 'canceled' | string;
  dry_run: boolean;
  preserved_percent?: number | null;
  fidelity_tier?: string | null;
  validation_verdict?: string | null;
  lint_verdict?: string | null;
  delivery_decision?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  options?: Record<string, unknown> | null;
  deliveries: ExportRunDelivery[];
  created_at: string;
  finished_at: string;
}

/** One target's stored reports (mirror of REST `ExportRunTargetReport`). */
export interface ExportRunTargetReport {
  target?: string | null;
  fidelity?: Record<string, unknown> | null;
  validation?: Record<string, unknown> | null;
  delivery_gate?: Record<string, unknown> | null;
}

/** One run with its stored reports (mirror of REST `ExportRunDetail`). */
export interface ExportRunDetail extends ExportRunSummary {
  reports: ExportRunTargetReport[];
}

/** A page of the history. */
export interface ExportRunPage {
  runs: ExportRunSummary[];
  total: number;
  limit: number;
  offset: number;
}

/** Someone in the history. */
export interface ExportRunActor {
  actor_id: string;
  actor_label: string;
}

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

/** The outcomes a run can end in. */
export const RUN_STATES = ['completed', 'failed', 'canceled'] as const;
/** The delivery channels, plus `none` (never delivered). */
export const RUN_CHANNELS = ['git', 'webhook', 'object-storage', 'none'] as const;
/** The validation verdicts. */
export const RUN_VALIDATIONS = ['valid', 'invalid', 'skipped', 'not_applicable'] as const;
/** The delivery decisions. */
export const RUN_DECISIONS = ['allow', 'allow_with_warning', 'block'] as const;

/** The history's filters; an empty string is "any". */
export interface HistoryFilters {
  artifact: string;
  target: string;
  actor: string;
  state: string;
  channel: string;
  validation: string;
  decision: string;
  /** `YYYY-MM-DD`, inclusive, in UTC. */
  from: string;
  /** `YYYY-MM-DD`, inclusive, in UTC. */
  to: string;
}

/** No filter. */
export const EMPTY_FILTERS: HistoryFilters = {
  artifact: '',
  target: '',
  actor: '',
  state: '',
  channel: '',
  validation: '',
  decision: '',
  from: '',
  to: '',
};

/** Rows per page. */
export const HISTORY_PAGE_SIZE = 25;

const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Whether any filter is set. */
export function hasFilters(filters: HistoryFilters): boolean {
  return Object.values(filters).some((value) => value !== '');
}

/** How many filters are set — the *Clear filters (n)* count. */
export function activeFilterCount(filters: HistoryFilters): number {
  return Object.values(filters).filter((value) => value !== '').length;
}

/**
 * The query string of one page of the history. A value outside its allowed set (a hand-edited URL) is
 * left out rather than sent; dates become whole UTC days.
 *
 * @param filters The filters.
 * @param page Zero-based page.
 * @param pageSize Rows per page.
 * @returns The query string, without the `?`.
 */
export function historyQuery(filters: HistoryFilters, page = 0, pageSize = HISTORY_PAGE_SIZE): string {
  const query = new URLSearchParams();
  const allowed: Array<[keyof HistoryFilters, readonly string[] | null]> = [
    ['artifact', null],
    ['target', null],
    ['actor', null],
    ['state', RUN_STATES],
    ['channel', RUN_CHANNELS],
    ['validation', RUN_VALIDATIONS],
    ['decision', RUN_DECISIONS],
  ];
  for (const [key, values] of allowed) {
    const value = filters[key].trim();
    if (value && (values === null || values.includes(value))) query.set(key, value);
  }
  if (DATE.test(filters.from)) query.set('finished_after', `${filters.from}T00:00:00Z`);
  if (DATE.test(filters.to)) query.set('finished_before', `${filters.to}T23:59:59Z`);
  query.set('limit', String(pageSize));
  query.set('offset', String(Math.max(0, page) * pageSize));
  return query.toString();
}

// ---------------------------------------------------------------------------
// Words and tones
// ---------------------------------------------------------------------------

/** A label and a status tone (the badge vocabulary). */
export interface Verdict {
  label: string;
  tone: 'ok' | 'warn' | 'danger' | 'neutral';
}

const STATE_VERDICTS: Record<string, Verdict> = {
  completed: { label: 'Completed', tone: 'ok' },
  failed: { label: 'Failed', tone: 'danger' },
  canceled: { label: 'Canceled', tone: 'neutral' },
};
const VALIDATION_VERDICTS: Record<string, Verdict> = {
  valid: { label: 'Valid', tone: 'ok' },
  invalid: { label: 'Invalid', tone: 'danger' },
  skipped: { label: 'Skipped', tone: 'warn' },
  not_applicable: { label: 'Not checked', tone: 'neutral' },
};
const LINT_VERDICTS: Record<string, Verdict> = {
  pass: { label: 'Pass', tone: 'ok' },
  warn: { label: 'Warnings', tone: 'warn' },
  block: { label: 'Blocking', tone: 'danger' },
};
const DECISION_VERDICTS: Record<string, Verdict> = {
  allow: { label: 'Allowed', tone: 'ok' },
  allow_with_warning: { label: 'Allowed with warnings', tone: 'warn' },
  block: { label: 'Blocked', tone: 'danger' },
};
const CHANNEL_LABELS: Record<string, string> = {
  git: 'Git',
  webhook: 'Webhook',
  'object-storage': 'Object storage',
  none: 'Not delivered',
};

/** A run's outcome in words. */
export function stateVerdict(state: string): Verdict {
  return STATE_VERDICTS[state] ?? { label: state, tone: 'neutral' };
}

/** A validation verdict in words, or null when the run never got that far. */
export function validationVerdict(verdict: string | null | undefined): Verdict | null {
  return verdict ? (VALIDATION_VERDICTS[verdict] ?? { label: verdict, tone: 'neutral' }) : null;
}

/** A lint verdict in words, or null. */
export function lintVerdict(verdict: string | null | undefined): Verdict | null {
  return verdict ? (LINT_VERDICTS[verdict] ?? { label: verdict, tone: 'neutral' }) : null;
}

/** A delivery decision in words, or null. */
export function decisionVerdict(decision: string | null | undefined): Verdict | null {
  return decision ? (DECISION_VERDICTS[decision] ?? { label: decision, tone: 'neutral' }) : null;
}

/** A delivery channel in words. */
export function channelLabel(channel: string): string {
  return CHANNEL_LABELS[channel] ?? channel;
}

/** The tone of a preserved share: all of it, most of it, or a real loss. */
export function preservedTone(percent: number | null | undefined): Verdict['tone'] {
  if (percent == null) return 'neutral';
  if (percent >= 100) return 'ok';
  if (percent >= 80) return 'warn';
  return 'danger';
}

/** `Petstore @ 1.4.0` — the source and its version, falling back to the ids. */
export function sourceLabel(run: Pick<ExportRunSummary, 'artifact_id' | 'artifact_name' | 'version_label'>): string {
  const name = run.artifact_name || run.artifact_id;
  return run.version_label ? `${name} @ ${run.version_label}` : name;
}

/**
 * Each channel's deliveries in one phrase, e.g. `Git delivered · Webhook failed`; a channel delivered
 * several times counts them (`Git delivered ×2`). `null` when the run was never delivered.
 *
 * @param deliveries The run's deliveries.
 * @returns The phrase, or null.
 */
export function deliverySummary(deliveries: ExportRunDelivery[]): string | null {
  if (deliveries.length === 0) return null;
  const counts = new Map<string, number>();
  for (const delivery of deliveries) {
    const key = `${delivery.channel}|${delivery.outcome}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts]
    .map(([key, count]) => {
      const [channel, outcome] = key.split('|');
      const word = outcome === 'in_progress' ? 'in progress' : outcome;
      return `${channelLabel(channel)} ${word}${count > 1 ? ` ×${count}` : ''}`;
    })
    .join(' · ');
}

// ---------------------------------------------------------------------------
// Re-run
// ---------------------------------------------------------------------------

/**
 * The Export studio link that re-runs a run: its source and revision, its target and its options
 * pre-filled, opening on **Options** so they can be reviewed before generating. A multi-target run has
 * no single target to pre-select, so it opens on **Target**.
 *
 * @param run The run.
 * @returns The Studio deep link.
 */
export function rerunHref(run: ExportRunSummary): string {
  const single = run.target && !run.target.includes(',') ? run.target : null;
  return exportStudioHref({
    artifact: run.artifact_id,
    version: run.version_record_id || run.version_label || null,
    label: run.artifact_name || null,
    target: single,
    options: single ? (run.options ?? null) : null,
    step: single ? 'options' : 'target',
  });
}
