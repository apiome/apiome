/**
 * Client contract for applying deterministic lint fixes from the UI — GVM-3.6 (#5874).
 *
 * The REST side (GVM-3.2, #5870) plans a revision's mechanical fixes (`GET …/lint/fixes`) and
 * applies them as a **new** `lint-fix` revision (`POST …/lint/fixes/apply`), re-linting it and
 * storing its report. This module is the one place the UI talks to that contract, through the
 * BFF routes under `/api/projects/[projectId]/versions/[versionId]/lint/fixes`:
 *
 * - the wire types and defensive parsers for a plan and an apply result,
 * - `fetchLintFixPlan` / `applyLintFixes`, which raise {@link LintFixError} carrying the
 *   server's refusal `code` (e.g. `lint-fix-version-published`, `lint-fix-breaking`),
 * - pure helpers both surfaces share: matching a plan entry to a finding, the sentence a
 *   non-ready entry renders, which posture subjects can be fixed at all, and
 *   {@link observeFixedFindings}, which reads the new revision's re-lint to say which findings
 *   are actually gone (the posture marks a finding `fixed` only when it is observed gone).
 *
 * The Lint report dialog (Versions screen) and the Lint posture drawer and bulk bar consume it;
 * the Designer Studio consumes the same BFF contract.
 */

import type { VersionLintReport } from './version-lint-report';

// --- Vocabulary ---------------------------------------------------------------------------------

/** Status of one plan entry, as the REST plan states it. */
export type LintFixStatus = 'ready' | 'conflict' | 'breaking' | 'excluded';

/** The subject type of a posture finding raised on a catalog revision (has a document). */
export const FIXABLE_SUBJECT_TYPE = 'catalog_revision';

/** The subject type of a posture finding raised on an MCP endpoint version (no document). */
export const MCP_SUBJECT_TYPE = 'mcp_endpoint_version';

/** Refusal code the REST apply returns for a published revision. */
export const LINT_FIX_PUBLISHED_CODE = 'lint-fix-version-published';

/** Why a published revision's fixes are read-only (mirrors the REST 409 message). */
export const PUBLISHED_REASON =
  'This revision is published, so fixes cannot be applied to it. Apply them to a draft revision.';

/** Why an MCP endpoint finding has no Apply fix. */
export const MCP_NO_DOCUMENT_REASON =
  'MCP endpoint findings have no document to fix: the finding is on the live server, not on a stored revision.';

/** What a finding without a plan entry says. */
export const NO_FIX_REASON = 'This rule has no deterministic fix for this finding.';

/** Upper bound on an apply reason, matching the REST request model. */
export const MAX_FIX_REASON_LENGTH = 2000;

/** Sentence for each `excluded` reason code the planner emits. */
const EXCLUDED_REASON_TEXT: Record<string, string> = {
  'not-selected': 'Not selected for this plan.',
  'guide-disabled': "The project's style guide turns this rule off.",
  'renames-not-included':
    'A rename fix: it changes names clients use, so it is only applied on request.',
  'opt-in-required': 'This fix is off by default and must be requested by rule.',
};

// --- Wire types ---------------------------------------------------------------------------------

/** One fixable finding of a plan. */
export interface LintFixEntry {
  fixId: string;
  ruleId: string;
  fixClass: string;
  wireVisible: boolean;
  path: string;
  pointer: string;
  findingId: string;
  message: string;
  status: LintFixStatus;
  /** Why an `excluded` entry was excluded (a reason code), else null. */
  reason: string | null;
  /** For a `conflict`, the fix id of the ready fix that wins the subtree. */
  conflictsWith: string | null;
  /** Classified changes of the fix's own delta (used to explain a `breaking` entry). */
  changes: Array<{ ruleId: string; severity: string; pointer: string }>;
}

/** A revision's lint-fix plan, plus whether the revision is published (BFF enrichment). */
export interface LintFixPlan {
  projectId: string | null;
  versionRecordId: string | null;
  counts: Record<string, number>;
  entries: LintFixEntry[];
  /** Whether the stored report still matches the planned document. */
  reportCurrent: boolean | null;
  /** True when the revision is published: the plan is read-only. */
  published: boolean;
}

/** The revision an apply created. */
export interface LintFixApplyResult {
  projectId: string;
  sourceVersionRecordId: string;
  versionRecordId: string;
  versionLabel: string;
  appliedFixIds: string[];
  skipped: Array<{ fixId: string; ruleId: string; status: string }>;
  score: number | null;
  grade: string | null;
}

/** A refused or failed lint-fix call; `code` is the server's refusal code when it sent one. */
export class LintFixError extends Error {
  /** The structured refusal code (`lint-fix-…`), or null. */
  readonly code: string | null;
  /** The HTTP status. */
  readonly status: number;

  /**
   * @param message The sentence to show.
   * @param code The refusal code, when the server sent one.
   * @param status The HTTP status.
   */
  constructor(message: string, code: string | null, status: number) {
    super(message);
    this.name = 'LintFixError';
    this.code = code;
    this.status = status;
  }
}

// --- Parsers ------------------------------------------------------------------------------------

/** Read `v` as a plain object (or an empty one). */
function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

/** Read `v` as a string, or `fallback`. */
function str(v: unknown, fallback = ''): string {
  return typeof v === 'string' ? v : fallback;
}

/** Read `v` as a non-empty string, or null. */
function strOrNull(v: unknown): string | null {
  return typeof v === 'string' && v ? v : null;
}

const STATUSES: readonly LintFixStatus[] = ['ready', 'conflict', 'breaking', 'excluded'];

/**
 * Parse one plan entry defensively.
 *
 * @param v The raw entry.
 * @returns The entry, or null when it has no fix id.
 */
export function lintFixEntryFromPayload(v: unknown): LintFixEntry | null {
  const raw = asRecord(v);
  const fixId = str(raw.fixId);
  if (!fixId) return null;
  const status = STATUSES.includes(raw.status as LintFixStatus)
    ? (raw.status as LintFixStatus)
    : 'excluded';
  const classification = asRecord(raw.classification);
  const changes = Array.isArray(classification.changes)
    ? classification.changes.map((c) => {
        const change = asRecord(c);
        return {
          ruleId: str(change.ruleId),
          severity: str(change.severity),
          pointer: str(change.pointer),
        };
      })
    : [];
  return {
    fixId,
    ruleId: str(raw.ruleId),
    fixClass: str(raw.fixClass),
    wireVisible: raw.wireVisible === true,
    path: str(raw.path),
    pointer: str(raw.pointer),
    findingId: str(raw.findingId),
    message: str(raw.message),
    status,
    reason: strOrNull(raw.reason),
    conflictsWith: strOrNull(raw.conflictsWith),
    changes,
  };
}

/**
 * Parse a plan payload (the BFF's `{ success, …plan, published }`).
 *
 * @param v The raw body.
 * @returns The plan.
 */
export function lintFixPlanFromPayload(v: unknown): LintFixPlan {
  const raw = asRecord(v);
  const counts: Record<string, number> = {};
  for (const [key, value] of Object.entries(asRecord(raw.counts))) {
    if (typeof value === 'number') counts[key] = value;
  }
  return {
    projectId: strOrNull(raw.projectId),
    versionRecordId: strOrNull(raw.versionRecordId),
    counts,
    entries: (Array.isArray(raw.entries) ? raw.entries : [])
      .map(lintFixEntryFromPayload)
      .filter((entry): entry is LintFixEntry => entry !== null),
    reportCurrent: typeof raw.reportCurrent === 'boolean' ? raw.reportCurrent : null,
    published: raw.published === true,
  };
}

/**
 * Parse an apply payload.
 *
 * @param v The raw body.
 * @returns The created revision.
 */
export function lintFixApplyResultFromPayload(v: unknown): LintFixApplyResult {
  const raw = asRecord(v);
  return {
    projectId: str(raw.projectId),
    sourceVersionRecordId: str(raw.sourceVersionRecordId),
    versionRecordId: str(raw.versionRecordId),
    versionLabel: str(raw.versionLabel),
    appliedFixIds: Array.isArray(raw.appliedFixIds)
      ? raw.appliedFixIds.filter((id): id is string => typeof id === 'string')
      : [],
    skipped: (Array.isArray(raw.skipped) ? raw.skipped : []).map((s) => {
      const skip = asRecord(s);
      return { fixId: str(skip.fixId), ruleId: str(skip.ruleId), status: str(skip.status) };
    }),
    score: typeof raw.score === 'number' ? raw.score : null,
    grade: strOrNull(raw.grade),
  };
}

/**
 * Turn a failed BFF body into a {@link LintFixError}.
 *
 * REST refusals carry `detail: { code, message }`; the BFF spreads it into the body.
 *
 * @param data The parsed body (may be null).
 * @param status The HTTP status.
 * @param fallback What to say when the body carried nothing.
 * @returns The error.
 */
export function lintFixErrorFromPayload(
  data: unknown,
  status: number,
  fallback: string,
): LintFixError {
  const raw = asRecord(data);
  const detail = raw.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const d = asRecord(detail);
    return new LintFixError(str(d.message, fallback), strOrNull(d.code), status);
  }
  if (Array.isArray(detail) && detail.length > 0) {
    // FastAPI validation errors: [{ msg, … }].
    return new LintFixError(str(asRecord(detail[0]).msg, fallback), null, status);
  }
  const message = typeof detail === 'string' && detail ? detail : str(raw.error, fallback);
  return new LintFixError(message || fallback, strOrNull(raw.code), status);
}

// --- Requests -----------------------------------------------------------------------------------

/** The BFF base path of a revision's lint fixes. */
function fixesPath(projectId: string, versionId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(versionId)}/lint/fixes`;
}

/**
 * Fetch a revision's lint-fix plan (every rule its style guide turns on, no renames).
 *
 * @param projectId The project.
 * @param versionId The revision (`versions.id`).
 * @param options Optional abort signal.
 * @returns The plan, with `published` set by the BFF.
 * @throws LintFixError when the plan cannot be read (e.g. `lint-fix-not-openapi`).
 */
export async function fetchLintFixPlan(
  projectId: string,
  versionId: string,
  options?: { signal?: AbortSignal },
): Promise<LintFixPlan> {
  const response = await fetch(fixesPath(projectId, versionId), {
    method: 'GET',
    credentials: 'include',
    cache: 'no-store',
    signal: options?.signal,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || (data as { success?: unknown }).success === false) {
    throw lintFixErrorFromPayload(data, response.status, 'Could not plan the lint fixes.');
  }
  return lintFixPlanFromPayload(data);
}

/**
 * Apply fixes to a revision, creating a new `lint-fix` revision.
 *
 * @param projectId The project.
 * @param versionId The source revision.
 * @param fixIds The ready fixes to apply.
 * @param reason Why (audited; required, non-blank).
 * @returns The created revision.
 * @throws LintFixError on a refusal (published, breaking, conflict, …) or failure.
 */
export async function applyLintFixes(
  projectId: string,
  versionId: string,
  fixIds: readonly string[],
  reason: string,
): Promise<LintFixApplyResult> {
  const trimmed = reason.trim();
  if (!trimmed) throw new LintFixError('Give a reason for applying the fixes.', null, 400);
  if (fixIds.length === 0) throw new LintFixError('There are no fixes to apply.', null, 400);
  const response = await fetch(`${fixesPath(projectId, versionId)}/apply`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fixIds: [...fixIds], reason: trimmed.slice(0, MAX_FIX_REASON_LENGTH) }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || (data as { success?: unknown }).success === false) {
    throw lintFixErrorFromPayload(data, response.status, 'Could not apply the lint fixes.');
  }
  return lintFixApplyResultFromPayload(data);
}

// --- Pure helpers -------------------------------------------------------------------------------

/**
 * Index a plan's entries by the finding they repair.
 *
 * @param plan The plan, or null.
 * @returns Finding id → entry.
 */
export function fixEntriesByFinding(plan: LintFixPlan | null): Map<string, LintFixEntry> {
  const out = new Map<string, LintFixEntry>();
  for (const entry of plan?.entries ?? []) {
    if (entry.findingId) out.set(entry.findingId, entry);
  }
  return out;
}

/**
 * The plan entry for one finding: by finding id, falling back to rule + path.
 *
 * @param plan The plan, or null.
 * @param finding The finding's id, rule and path.
 * @returns The entry, or null when the finding has no fix.
 */
export function fixEntryForFinding(
  plan: LintFixPlan | null,
  finding: { id?: string | null; rule?: string | null; path?: string | null },
): LintFixEntry | null {
  if (!plan) return null;
  if (finding.id) {
    const byId = plan.entries.find((entry) => entry.findingId === finding.id);
    if (byId) return byId;
  }
  if (!finding.rule) return null;
  return (
    plan.entries.find(
      (entry) => entry.ruleId === finding.rule && entry.path === (finding.path ?? ''),
    ) ?? null
  );
}

/**
 * The fixes an "Apply N deterministic fixes" button applies.
 *
 * @param plan The plan, or null.
 * @returns The fix ids of the ready entries, in plan order.
 */
export function readyFixIds(plan: LintFixPlan | null): string[] {
  return (plan?.entries ?? []).filter((entry) => entry.status === 'ready').map((e) => e.fixId);
}

/**
 * The sentence a non-ready entry renders in place of an Apply action.
 *
 * @param entry The entry.
 * @returns The reason, or null for a `ready` entry.
 */
export function fixEntryReason(entry: LintFixEntry): string | null {
  switch (entry.status) {
    case 'ready':
      return null;
    case 'breaking': {
      const breaking = entry.changes.filter((c) => c.severity === 'breaking').map((c) => c.ruleId);
      const which = breaking.length ? ` (${[...new Set(breaking)].join(', ')})` : '';
      return `Not applied: this fix makes a breaking change${which}, so it needs a human.`;
    }
    case 'conflict':
      return entry.conflictsWith
        ? `Not applied: it edits the same part of the document as ${entry.conflictsWith}. Apply that fix first, then plan again.`
        : 'Not applied: it edits the same part of the document as another fix. Apply that one first, then plan again.';
    case 'excluded':
      return EXCLUDED_REASON_TEXT[entry.reason ?? ''] ?? 'Not part of the default plan.';
    default:
      return null;
  }
}

/** Whether a posture finding can carry an Apply fix, and why not when it cannot. */
export interface FixSubjectSupport {
  supported: boolean;
  reason: string | null;
}

/**
 * Whether a posture finding is on a subject that has a document to fix.
 *
 * @param finding The finding's subject fields.
 * @returns `supported`, or the reason it is not.
 */
export function fixSubjectSupport(finding: {
  subjectType: string;
  projectId: string | null;
  versionRecordId: string | null;
  sourceFingerprint: string | null;
}): FixSubjectSupport {
  if (finding.subjectType === MCP_SUBJECT_TYPE) {
    return { supported: false, reason: MCP_NO_DOCUMENT_REASON };
  }
  if (
    finding.subjectType !== FIXABLE_SUBJECT_TYPE ||
    !finding.projectId ||
    !finding.versionRecordId
  ) {
    return { supported: false, reason: 'This finding is not on a stored catalog revision.' };
  }
  if (!finding.sourceFingerprint) {
    return { supported: false, reason: 'This finding has no stable id to match a fix to.' };
  }
  return { supported: true, reason: null };
}

/**
 * Which applied findings the new revision's re-lint no longer reports.
 *
 * This is the "observed, not assumed" check: a finding is fixed when the stored report of the
 * revision the apply created does not contain it (by id, or by rule + path).
 *
 * @param report The new revision's lint report.
 * @param findings The findings the applied fixes targeted.
 * @returns `fixed` (gone from the report) and `remaining` (still reported), by finding id.
 */
export function observeFixedFindings(
  report: Pick<VersionLintReport, 'findings'>,
  findings: ReadonlyArray<{ id: string; rule: string; path: string }>,
): { fixed: string[]; remaining: string[] } {
  const ids = new Set(report.findings.map((f) => f.id));
  const rulePaths = new Set(report.findings.map((f) => `${f.rule}\u0000${f.path}`));
  const fixed: string[] = [];
  const remaining: string[] = [];
  for (const finding of findings) {
    const present = ids.has(finding.id) || rulePaths.has(`${finding.rule}\u0000${finding.path}`);
    (present ? remaining : fixed).push(finding.id);
  }
  return { fixed, remaining };
}

/**
 * The Versions screen route that lists a revision's project.
 *
 * @param projectId The project.
 * @returns The href.
 */
export function revisionHref(projectId: string): string {
  return `/ade/dashboard/versions?projectId=${encodeURIComponent(projectId)}`;
}

/**
 * The default reason prefilled in the apply dialog.
 *
 * @param count How many fixes are applied.
 * @param ruleId The rule, when a single fix is applied.
 * @returns The sentence.
 */
export function defaultFixReason(count: number, ruleId?: string | null): string {
  if (count === 1 && ruleId) return `Apply the deterministic ${ruleId} fix.`;
  return `Apply ${count} deterministic lint fix${count === 1 ? '' : 'es'}.`;
}
