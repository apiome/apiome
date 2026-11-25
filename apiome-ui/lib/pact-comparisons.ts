/**
 * Bi-directional comparisons and their fidelity reports in the UI — PFX-2.5 (#6929).
 *
 * The wire shapes of `GET /v1/tenants/{tenant}/pact-comparisons` and
 * `GET /v1/tenants/{tenant}/pact-comparisons/{resultId}/fidelity`, and the pure rules the
 * **Pact comparisons** page draws them with. A green verdict is only as strong as the report's
 * `strength` says, so every label here pairs a verdict with what was *not* compared — the page
 * never shows "Pass" alone when part of the pact was not compared in full.
 */

import type { BadgeTone } from '@/app/components/ui/Badge';

/** A check's status in the report. */
export type FidelityCheckStatus = 'compared' | 'partial' | 'failed' | 'not-run';

/** How strong a comparison's answer is. */
export type FidelityStrength = 'full' | 'partial' | 'failed' | 'none';

/** A stored verdict, `unverified` included (PFX-2.4). */
export type ComparisonVerdict = 'pass' | 'partial' | 'fail' | 'unverified';

/** One check of one interaction. */
export interface FidelityCheck {
  check: string;
  label: string;
  status: FidelityCheckStatus;
  /** Why a `not-run` check did not run. */
  reason?: string;
  failures: number;
  warnings: number;
  notes: number;
}

/** One thing the comparison did not vouch for. */
export interface FidelityNote {
  code: string;
  message: string;
  pactPointer: string;
  /** The check it belongs to, or `null` for the interaction as a whole. */
  check: string | null;
  reason?: string;
  oasPointer?: string;
  matcher?: string;
  constraint?: Record<string, unknown>;
}

/** The report of one interaction. */
export interface FidelityInteraction {
  index: number;
  description: string | null;
  pointer: string;
  verdict: 'pass' | 'partial' | 'fail';
  operation: { method: string; path: string; pointer: string; operationId: string | null } | null;
  checks: FidelityCheck[];
  matchingRules: Partial<Record<'total' | 'verified' | 'unverified' | 'notMapped', number>>;
  unsupportedMatchingRules: FidelityNote[];
  couldNotCompare: FidelityNote[];
  failures: number;
  warnings: number;
}

/** The report's counts. */
export interface FidelitySummary {
  interactions: number;
  fullyCompared: number;
  partial: number;
  failed: number;
  notCompared: number;
  checksCompared: number;
  checksPartial: number;
  checksFailed: number;
  checksNotRun: number;
  unsupportedMatchingRules: number;
  couldNotCompare: number;
}

/** Who and what a result is about. */
export interface ComparisonIdentity {
  id: string;
  number: number;
  consumer: { name: string; slug: string; version: string | null };
  provider: { name: string; slug: string; version: string; branch: string | null };
  pactVersionSha: string;
  success: boolean;
  createdAt: string | null;
}

/** One row of the comparisons list. */
export interface ComparisonListEntry extends ComparisonIdentity {
  verdict: ComparisonVerdict;
  comparisonVerdict: ComparisonVerdict;
  strength: FidelityStrength;
  statement: string;
  selfVerification: string | null;
  summary: FidelitySummary;
  fidelityPath: string;
}

/** The list response. */
export interface ComparisonListResponse {
  comparisons: ComparisonListEntry[];
  limit: number;
}

/** The fidelity report of one result. */
export interface ComparisonFidelityReport {
  result: ComparisonIdentity;
  verdict: ComparisonVerdict;
  comparisonVerdict: ComparisonVerdict;
  strength: FidelityStrength;
  statement: string;
  selfVerification: string | null;
  providerContractSha: string | null;
  consumer: string | null;
  provider: string | null;
  pactSpecification: string | null;
  oasVersion: string | null;
  summary: FidelitySummary;
  interactions: FidelityInteraction[];
  error?: { code: string; message: string };
}

/** What each check status reads as next to its icon (colour is never the only signal). */
export const CHECK_STATUS_LABELS: Readonly<Record<FidelityCheckStatus, string>> = {
  compared: 'Compared',
  partial: 'Partly compared',
  failed: 'Failed',
  'not-run': 'Not run',
};

/** What each strength reads as. */
export const STRENGTH_LABELS: Readonly<Record<FidelityStrength, string>> = {
  full: 'Compared in full',
  partial: 'Not everything compared',
  failed: 'Contradicts the pact',
  none: 'Nothing compared',
};

/** The tone of each strength: only a full comparison is green. */
export const STRENGTH_TONES: Readonly<Record<FidelityStrength, BadgeTone>> = {
  full: 'ok',
  partial: 'warn',
  failed: 'danger',
  none: 'neutral',
};

/** What each verdict reads as. */
export const VERDICT_LABELS: Readonly<Record<ComparisonVerdict, string>> = {
  pass: 'Pass',
  partial: 'Pass (partial)',
  fail: 'Fail',
  unverified: 'Unverified',
};

/** The tone of each verdict. */
export const VERDICT_TONES: Readonly<Record<ComparisonVerdict, BadgeTone>> = {
  pass: 'ok',
  partial: 'warn',
  fail: 'danger',
  unverified: 'warn',
};

/**
 * The verdict and its strength as one honest label, e.g. `Pass · Not everything compared`.
 *
 * A `pass` with a `full` strength reads `Pass · Compared in full`; anything weaker says so.
 *
 * @param verdict - The stored verdict.
 * @param strength - The report's strength.
 * @returns The label.
 */
export function verdictLabel(verdict: ComparisonVerdict, strength: FidelityStrength): string {
  const name = VERDICT_LABELS[verdict] ?? verdict;
  return `${name} · ${STRENGTH_LABELS[strength] ?? strength}`;
}

/**
 * The counts that matter for one list row, e.g. `3 interactions · 2 not compared · 1 rule unsupported`.
 *
 * @param summary - The report's counts.
 * @returns The line, zero counts left out.
 */
export function summaryLine(summary: FidelitySummary): string {
  const parts = [`${summary.interactions} interaction${summary.interactions === 1 ? '' : 's'}`];
  if (summary.failed) parts.push(`${summary.failed} failed`);
  if (summary.couldNotCompare) parts.push(`${summary.couldNotCompare} not compared`);
  if (summary.unsupportedMatchingRules) {
    parts.push(`${summary.unsupportedMatchingRules} rule${summary.unsupportedMatchingRules === 1 ? '' : 's'} unsupported`);
  }
  if (summary.checksNotRun) parts.push(`${summary.checksNotRun} check${summary.checksNotRun === 1 ? '' : 's'} not run`);
  return parts.join(' · ');
}

/**
 * How an interaction is named: its description, else `Interaction 3`.
 *
 * @param interaction - The interaction.
 * @returns The name.
 */
export function interactionName(interaction: Pick<FidelityInteraction, 'description' | 'index'>): string {
  return interaction.description?.trim() || `Interaction ${interaction.index + 1}`;
}

/**
 * The matched operation as `GET /invoices/{id}`, or `null` when none was resolved.
 *
 * @param interaction - The interaction.
 * @returns The operation line.
 */
export function operationLine(interaction: Pick<FidelityInteraction, 'operation'>): string | null {
  const operation = interaction.operation;
  return operation ? `${operation.method.toUpperCase()} ${operation.path}` : null;
}

/** A verification result id, as the fidelity route accepts. */
const RESULT_ID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

/**
 * The REST path (below `/v1/tenants/{slug}`) of a result's fidelity report, or `null` for a
 * malformed id — the proxy then answers 404 without calling apiome-rest.
 *
 * @param id - The verification result id.
 * @returns The path, or `null`.
 */
export function fidelityProxyPath(id: string): string | null {
  return RESULT_ID.test(id) ? `pact-comparisons/${id.toLowerCase()}/fidelity` : null;
}

/**
 * The REST path of the comparisons list, carrying `limit` only when it is a whole number in 1 … 100.
 *
 * @param limit - The `limit` query parameter as the browser sent it, if any.
 * @returns The path below `/v1/tenants/{slug}`.
 */
export function listProxyPath(limit: string | null): string {
  const value = limit === null ? NaN : Number(limit);
  return Number.isInteger(value) && value >= 1 && value <= 100 ? `pact-comparisons?limit=${value}` : 'pact-comparisons';
}
