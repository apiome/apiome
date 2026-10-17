/**
 * The rules of the bulk convert review (MFI-28.5, #4121).
 *
 * Converting several catalog items to OpenAPI is still the EPIC-22 fidelity-gated flow, once
 * per item: each item gets its own dry-run, its own fidelity grade and tier, and — for a
 * `low`-tier conversion — its own acknowledgement before it may be committed. The one
 * shortcut the ticket allows is an *explicit* "apply the fidelity warning to all" gate, which
 * stands in for every per-item acknowledgement at once and says so in its label.
 *
 * Everything the dialog decides — which rows are queued, whether Convert is allowed and why
 * not, what the outcome line says — is here, so it is assertable without mounting a dialog.
 * The dialog itself only fetches, commits and draws.
 */

import { tierWarning, type FidelityReport } from '@/app/utils/conversion-fidelity';

import type { CatalogBulkFailure, CatalogItem } from './catalogModel';

/** Where one item is in the review. */
export type BulkConvertStatus =
  /** Its dry-run is in flight. */
  | 'previewing'
  /** Previewed; it can be converted once its gate (if any) is satisfied. */
  | 'ready'
  /** Its dry-run failed, so there is no report to convert against. */
  | 'preview-failed'
  /** Its commit is in flight. */
  | 'converting'
  /** Committed — a new OpenAPI project exists. */
  | 'converted'
  /** Its commit was refused; it can be tried again. */
  | 'failed';

/** One item in the bulk convert review. */
export interface BulkConvertRow {
  /** The catalog item's id (also its project id). */
  id: string;
  /** Its name. */
  name: string;
  /** Where it is in the review. */
  status: BulkConvertStatus;
  /** Its dry-run fidelity report, once previewed. */
  report: FidelityReport | null;
  /** The preview or commit failure, when there is one. */
  error: string | null;
  /** Whether the reader has kept it in the batch (all rows start included). */
  included: boolean;
  /** Its own low-tier acknowledgement. Ignored for a tier that does not require one. */
  acknowledged: boolean;
  /** The project a successful commit created, when the server returned it. */
  projectId: string | null;
}

/**
 * One row per item, every one included and previewing.
 *
 * @param items The items the bulk bar's Convert reached — the plan's `convertible` rows.
 * @returns The review's starting rows, in the selection's order.
 */
export function bulkConvertInitialRows(items: readonly CatalogItem[]): BulkConvertRow[] {
  return items.map((item) => ({
    id: item.id,
    name: item.name,
    status: 'previewing',
    report: null,
    error: null,
    included: true,
    acknowledged: false,
    projectId: null,
  }));
}

/**
 * Whether a row's fidelity tier requires an acknowledgement before it may be committed —
 * the same rule as the single-item dialog (`tierWarning(tier).requiresAck`, low tier only).
 *
 * @param row The row.
 * @returns `true` for a previewed low-tier row.
 */
export function bulkConvertNeedsAck(row: BulkConvertRow): boolean {
  return row.report ? tierWarning(row.report.tier).requiresAck : false;
}

/**
 * Whether a row's gate is satisfied — no acknowledgement needed, its own given, or the
 * explicit apply-to-all gate ticked.
 *
 * @param row The row.
 * @param applyToAll Whether the reader ticked "apply the fidelity warning to all".
 * @returns `true` when the row may be committed as far as its fidelity gate goes.
 */
export function bulkConvertAcknowledged(row: BulkConvertRow, applyToAll: boolean): boolean {
  return !bulkConvertNeedsAck(row) || row.acknowledged || applyToAll;
}

/**
 * The rows Convert would commit now: included, previewed (or failed once and being retried),
 * and past their fidelity gate.
 *
 * @param rows Every row in the review.
 * @param applyToAll Whether the apply-to-all gate is ticked.
 * @returns The rows to commit, in order.
 */
export function bulkConvertQueue(
  rows: readonly BulkConvertRow[],
  applyToAll: boolean
): BulkConvertRow[] {
  return rows.filter(
    (row) =>
      row.included &&
      (row.status === 'ready' || row.status === 'failed') &&
      bulkConvertAcknowledged(row, applyToAll)
  );
}

/**
 * The included, convertible rows whose low-tier acknowledgement is still missing. While any
 * exist Convert stays disabled, rather than silently skipping them — a reader who left a row
 * ticked meant it to be converted.
 *
 * @param rows Every row in the review.
 * @param applyToAll Whether the apply-to-all gate is ticked.
 * @returns The rows waiting on an acknowledgement.
 */
export function bulkConvertAwaitingAck(
  rows: readonly BulkConvertRow[],
  applyToAll: boolean
): BulkConvertRow[] {
  return rows.filter(
    (row) =>
      row.included &&
      (row.status === 'ready' || row.status === 'failed') &&
      !bulkConvertAcknowledged(row, applyToAll)
  );
}

/**
 * How many included rows carry a low-tier warning — what the apply-to-all gate would cover,
 * and whether it is offered at all (it is not when nothing needs acknowledging).
 *
 * @param rows Every row in the review.
 * @returns The count of included, convertible low-tier rows.
 */
export function bulkConvertLowTierCount(rows: readonly BulkConvertRow[]): number {
  return rows.filter(
    (row) =>
      row.included &&
      (row.status === 'ready' || row.status === 'failed') &&
      bulkConvertNeedsAck(row)
  ).length;
}

/**
 * Whether the explicit "apply the fidelity warning to all" gate is offered: only when two or
 * more included items need an acknowledgement. For one, the row's own checkbox already is
 * that acknowledgement, and an "all 1 item" gate would only say it twice.
 *
 * The dialog also treats a ticked gate as *unticked* while it is not offered, so a gate the
 * reader can no longer see never stands in for an acknowledgement.
 *
 * @param rows Every row in the review.
 * @returns `true` when the gate is shown and in force.
 */
export function bulkConvertOffersApplyToAll(rows: readonly BulkConvertRow[]): boolean {
  return bulkConvertLowTierCount(rows) > 1;
}

/** Whether Convert may be pressed, and the sentence to show when it may not. */
export interface BulkConvertGate {
  /** `true` when Convert may run. */
  canConvert: boolean;
  /** Why not, for the footer — `null` when it can. */
  reason: string | null;
}

/**
 * Whether the bulk Convert button is enabled.
 *
 * @param rows Every row in the review.
 * @param applyToAll Whether the apply-to-all gate is ticked.
 * @param busy Whether a commit run is in flight.
 * @returns The gate. See {@link BulkConvertGate}.
 */
export function bulkConvertGate(
  rows: readonly BulkConvertRow[],
  applyToAll: boolean,
  busy: boolean
): BulkConvertGate {
  if (busy) return { canConvert: false, reason: 'Converting…' };
  if (rows.some((row) => row.included && row.status === 'previewing')) {
    return { canConvert: false, reason: 'Previewing every item before anything is converted…' };
  }
  const waiting = bulkConvertAwaitingAck(rows, applyToAll).length;
  if (waiting > 0) {
    return {
      canConvert: false,
      reason: `Acknowledge the low-fidelity warning for ${waiting} ${waiting === 1 ? 'item' : 'items'}, or untick ${waiting === 1 ? 'it' : 'them'}.`,
    };
  }
  if (bulkConvertQueue(rows, applyToAll).length === 0) {
    return { canConvert: false, reason: 'Nothing left to convert.' };
  }
  return { canConvert: true, reason: null };
}

/**
 * The outcome line once a run has finished: the split, never only the successes.
 *
 * @param rows Every row in the review.
 * @returns e.g. `Converted 2 of 3 catalog items · 1 failed`, or `null` before any commit.
 */
export function bulkConvertSummary(rows: readonly BulkConvertRow[]): string | null {
  const converted = rows.filter((row) => row.status === 'converted').length;
  const failed = rows.filter((row) => row.status === 'failed').length;
  const attempted = converted + failed;
  if (attempted === 0) return null;
  const noun = attempted === 1 ? 'catalog item' : 'catalog items';
  if (failed === 0) return `Converted ${converted} ${noun}.`;
  return `Converted ${converted} of ${attempted} ${noun} · ${failed} failed`;
}

/**
 * The per-item failures to report — every row whose preview or commit failed, with its
 * reason (MFI-28.5: "partial failures are reported per item").
 *
 * @param rows Every row in the review.
 * @returns One entry per failed row.
 */
export function bulkConvertFailures(rows: readonly BulkConvertRow[]): CatalogBulkFailure[] {
  return rows
    .filter((row) => row.status === 'failed' || row.status === 'preview-failed')
    .map((row) => ({ id: row.id, name: row.name, reason: row.error ?? 'Failed to convert' }));
}

/**
 * What a row's status line says.
 *
 * @param row The row.
 * @returns A short phrase for the status column.
 */
export function bulkConvertStatusLabel(row: BulkConvertRow): string {
  switch (row.status) {
    case 'previewing':
      return 'Previewing…';
    case 'ready':
      return row.included ? 'Ready' : 'Skipped';
    case 'preview-failed':
      return 'Preview failed';
    case 'converting':
      return 'Converting…';
    case 'converted':
      return 'Converted';
    case 'failed':
    default:
      return 'Failed';
  }
}
