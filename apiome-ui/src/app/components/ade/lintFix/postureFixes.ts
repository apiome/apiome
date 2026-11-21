/**
 * Apply fix from the Lint posture workspace — GVM-3.6 (#5874).
 *
 * A posture finding is evidence on a subject. Only a **catalog revision** has a document to fix;
 * an MCP endpoint finding is on the live server and is skipped with the reason. For the
 * catalog-revision findings, grouped by revision:
 *
 * 1. plan the revision's fixes and match each finding to its entry (`sourceFingerprint` is the
 *    finding id the plan names; rule + path is the fallback);
 * 2. apply the `ready` entries with the reason — the server creates a new `lint-fix` revision,
 *    re-lints it and stores its report; `breaking` / `conflict` / `excluded` entries and a
 *    published revision are skipped with their reason;
 * 3. read the new revision's stored report and keep the findings it **no longer reports**
 *    ({@link observeFixedFindings}) — observed, not assumed;
 * 4. move exactly those to `fixed` through the bulk decision endpoint, with a rationale that
 *    names the new revision.
 *
 * The requests are injected so the flow is unit-testable without `fetch`.
 */

import type { LintWorkspaceBulkResponse, LintWorkspaceFinding } from '@/app/utils/lint-workspace';
import {
  NO_FIX_REASON,
  PUBLISHED_REASON,
  fixEntryForFinding,
  fixEntryReason,
  fixSubjectSupport,
  observeFixedFindings,
  type LintFixApplyResult,
  type LintFixPlan,
} from '@/app/utils/lint-fix';
import type { VersionLintReport } from '@/app/utils/version-lint-report';

/** The requests the flow makes. */
export interface PostureFixDeps {
  fetchPlan: (projectId: string, versionId: string) => Promise<LintFixPlan>;
  apply: (
    projectId: string,
    versionId: string,
    fixIds: readonly string[],
    reason: string,
  ) => Promise<LintFixApplyResult>;
  fetchReport: (projectId: string, versionId: string) => Promise<VersionLintReport>;
  /** Move findings to `fixed` with a rationale (the bulk decision endpoint). */
  markFixed: (
    findings: readonly LintWorkspaceFinding[],
    rationale: string,
  ) => Promise<LintWorkspaceBulkResponse>;
}

/** A finding the flow did not fix, and why. */
export interface PostureFixSkip {
  finding: LintWorkspaceFinding;
  reason: string;
}

/** What happened on one revision. */
export interface PostureFixRevision {
  projectId: string;
  sourceVersionRecordId: string;
  /** The revision the apply created, or null when nothing was applied. */
  result: LintFixApplyResult | null;
}

/** The outcome of one Apply fix (drawer or bulk bar). */
export interface PostureFixOutcome {
  revisions: PostureFixRevision[];
  /** Observed gone after the re-lint and moved to `fixed`. */
  fixed: LintWorkspaceFinding[];
  /** Applied, but the re-lint still reports them: left in their state. */
  remaining: LintWorkspaceFinding[];
  /** Not applied, with the reason. */
  skipped: PostureFixSkip[];
  /** The state the decision endpoint recorded, by source fingerprint. */
  states: Record<string, string>;
  /** Why marking the observed findings `fixed` failed, if it did. */
  markError: string | null;
}

/** The finding's id/rule/path, as the plan and report match them. */
function findingKey(finding: LintWorkspaceFinding): { id: string; rule: string; path: string } {
  const path = finding.location?.path;
  return {
    id: finding.sourceFingerprint ?? '',
    rule: finding.ruleId ?? '',
    path: typeof path === 'string' ? path : '',
  };
}

/** Turn a caught failure into a sentence. */
function message(caught: unknown, fallback: string): string {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}

/**
 * Split findings into those on a fixable subject and those that are not.
 *
 * @param findings The selection.
 * @returns `supported` findings and `skipped` ones with the reason (e.g. MCP endpoint).
 */
export function partitionFixableFindings(findings: readonly LintWorkspaceFinding[]): {
  supported: LintWorkspaceFinding[];
  skipped: PostureFixSkip[];
} {
  const supported: LintWorkspaceFinding[] = [];
  const skipped: PostureFixSkip[] = [];
  for (const finding of findings) {
    const support = fixSubjectSupport(finding);
    if (support.supported) supported.push(finding);
    else skipped.push({ finding, reason: support.reason ?? NO_FIX_REASON });
  }
  return { supported, skipped };
}

/**
 * Group fixable findings by the revision they are on.
 *
 * @param findings Findings on catalog revisions.
 * @returns `projectId|versionRecordId` → findings, in first-seen order.
 */
export function groupFindingsByRevision(
  findings: readonly LintWorkspaceFinding[],
): Map<string, LintWorkspaceFinding[]> {
  const groups = new Map<string, LintWorkspaceFinding[]>();
  for (const finding of findings) {
    const key = `${finding.projectId}|${finding.versionRecordId}`;
    const group = groups.get(key);
    if (group) group.push(finding);
    else groups.set(key, [finding]);
  }
  return groups;
}

/**
 * Run Apply fix over a set of posture findings.
 *
 * Revisions are processed one after another (each apply creates a revision and re-lints it).
 *
 * @param findings The findings (one from the drawer, or the bulk selection).
 * @param reason The audited reason.
 * @param deps The requests.
 * @returns The outcome.
 */
export async function applyPostureFixes(
  findings: readonly LintWorkspaceFinding[],
  reason: string,
  deps: PostureFixDeps,
): Promise<PostureFixOutcome> {
  const { supported, skipped } = partitionFixableFindings(findings);
  const outcome: PostureFixOutcome = {
    revisions: [],
    fixed: [],
    remaining: [],
    skipped,
    states: {},
    markError: null,
  };

  for (const group of groupFindingsByRevision(supported).values()) {
    const projectId = group[0].projectId as string;
    const versionId = group[0].versionRecordId as string;
    const revision: PostureFixRevision = {
      projectId,
      sourceVersionRecordId: versionId,
      result: null,
    };
    outcome.revisions.push(revision);

    let plan: LintFixPlan;
    try {
      plan = await deps.fetchPlan(projectId, versionId);
    } catch (caught) {
      const why = message(caught, 'Could not plan the lint fixes.');
      outcome.skipped.push(...group.map((finding) => ({ finding, reason: why })));
      continue;
    }

    const targeted: LintWorkspaceFinding[] = [];
    const fixIds: string[] = [];
    for (const finding of group) {
      const entry = fixEntryForFinding(plan, findingKey(finding));
      if (!entry) {
        outcome.skipped.push({ finding, reason: NO_FIX_REASON });
      } else if (entry.status !== 'ready') {
        outcome.skipped.push({ finding, reason: fixEntryReason(entry) ?? NO_FIX_REASON });
      } else if (plan.published) {
        outcome.skipped.push({ finding, reason: PUBLISHED_REASON });
      } else {
        targeted.push(finding);
        if (!fixIds.includes(entry.fixId)) fixIds.push(entry.fixId);
      }
    }
    if (fixIds.length === 0) continue;

    let result: LintFixApplyResult;
    try {
      result = await deps.apply(projectId, versionId, fixIds, reason);
    } catch (caught) {
      const why = message(caught, 'Could not apply the lint fixes.');
      outcome.skipped.push(...targeted.map((finding) => ({ finding, reason: why })));
      continue;
    }
    revision.result = result;

    // Observe: the new revision's stored report decides which findings are gone.
    let report: VersionLintReport;
    try {
      report = await deps.fetchReport(projectId, result.versionRecordId);
    } catch {
      outcome.remaining.push(...targeted);
      continue;
    }
    const observed = observeFixedFindings(report, targeted.map(findingKey));
    const gone = new Set(observed.fixed);
    const fixedHere = targeted.filter((finding) => gone.has(findingKey(finding).id));
    outcome.remaining.push(...targeted.filter((finding) => !gone.has(findingKey(finding).id)));
    if (fixedHere.length === 0) continue;

    try {
      const response = await deps.markFixed(
        fixedHere,
        `Fixed by lint-fix revision v${result.versionLabel}: ${reason}`,
      );
      for (const item of response.results) {
        if (item.ok && item.afterState) outcome.states[item.sourceFingerprint] = item.afterState;
      }
      outcome.fixed.push(
        ...fixedHere.filter(
          (finding) => outcome.states[finding.sourceFingerprint ?? ''] === 'fixed',
        ),
      );
      const refused = response.results.find((item) => !item.ok);
      if (refused) outcome.markError = refused.error ?? 'Some findings could not be marked fixed.';
    } catch (caught) {
      outcome.markError = message(caught, 'Could not mark the findings fixed.');
    }
  }

  return outcome;
}

/** What the toast for an outcome says. */
export interface PostureFixToast {
  tone: 'success' | 'warning' | 'error';
  title: string;
  description: string;
}

/**
 * The toast copy for an outcome.
 *
 * @param outcome The outcome.
 * @returns The tone, title and description.
 */
export function postureFixToast(outcome: PostureFixOutcome): PostureFixToast {
  const created = outcome.revisions
    .filter((r) => r.result)
    .map((r) => `v${r.result!.versionLabel}`);
  const fixed = outcome.fixed.length;
  const parts: string[] = [];
  if (created.length)
    parts.push(`New revision${created.length === 1 ? '' : 's'}: ${created.join(', ')}.`);
  if (outcome.remaining.length) {
    parts.push(`${outcome.remaining.length} still reported after the re-lint, left as they were.`);
  }
  if (outcome.skipped.length) {
    const first = outcome.skipped[0];
    parts.push(
      outcome.skipped.length === 1
        ? `Not applied: ${first.reason}`
        : `${outcome.skipped.length} not applied — e.g. ${first.reason}`,
    );
  }
  if (outcome.markError) parts.push(outcome.markError);
  const title =
    fixed > 0
      ? `Fixed ${fixed} finding${fixed === 1 ? '' : 's'}`
      : created.length > 0
        ? 'Fixes applied'
        : 'No fixes applied';
  const tone =
    created.length === 0
      ? 'error'
      : outcome.skipped.length || outcome.remaining.length || outcome.markError
        ? 'warning'
        : 'success';
  return { tone, title, description: parts.join(' ') };
}
