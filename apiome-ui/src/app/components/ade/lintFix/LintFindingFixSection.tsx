'use client';

import * as React from 'react';
import { Lock } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import {
  NO_FIX_REASON,
  PUBLISHED_REASON,
  fixEntryForFinding,
  fixEntryReason,
  fixSubjectSupport,
  type LintFixEntry,
  type LintFixPlan,
} from '@/app/utils/lint-fix';
import type { LintWorkspaceFinding } from '@/app/utils/lint-workspace';

import { LintFixResultNote } from './LintReportFixControls';
import type { PostureFixOutcome } from './postureFixes';

/**
 * The finding drawer's *Fix* section — GVM-3.6 (#5874).
 *
 * Says, for the one finding the drawer shows, whether a deterministic fix exists and whether it
 * can be applied here: an MCP endpoint finding has no document to fix; a published revision's
 * fix is read-only; a `breaking` or `conflict` fix renders its reason. After an apply it shows
 * the new revision and what the re-lint observed. The *Apply fix* verb itself is in the drawer
 * footer, next to the other decisions.
 */

/** What the drawer needs to know to draw its footer verb. */
export interface FindingFixState {
  /** The plan entry for the finding, when there is one. */
  entry: LintFixEntry | null;
  /** True when the entry is ready and the revision is a draft: *Apply fix* is offered. */
  canApply: boolean;
}

/**
 * Derive the drawer's fix state from a plan.
 *
 * @param finding The finding.
 * @param plan The revision's plan, or null.
 * @returns The entry and whether it can be applied.
 */
export function findingFixState(
  finding: LintWorkspaceFinding,
  plan: LintFixPlan | null,
): FindingFixState {
  if (!fixSubjectSupport(finding).supported || !plan) return { entry: null, canApply: false };
  const path = finding.location?.path;
  const entry = fixEntryForFinding(plan, {
    id: finding.sourceFingerprint,
    rule: finding.ruleId,
    path: typeof path === 'string' ? path : '',
  });
  return { entry, canApply: Boolean(entry && entry.status === 'ready' && !plan.published) };
}

/** Props for {@link LintFindingFixSection}. */
export interface LintFindingFixSectionProps {
  finding: LintWorkspaceFinding;
  plan: LintFixPlan | null;
  loading: boolean;
  error: string | null;
  /** The last Apply fix outcome that included this finding. */
  outcome: PostureFixOutcome | null;
}

/**
 * The section.
 *
 * @param props See {@link LintFindingFixSectionProps}.
 * @returns The heading and the one line that applies.
 */
export function LintFindingFixSection({
  finding,
  plan,
  loading,
  error,
  outcome,
}: LintFindingFixSectionProps) {
  const support = fixSubjectSupport(finding);
  const { entry } = findingFixState(finding, plan);
  const fingerprint = finding.sourceFingerprint ?? '';
  const revision = outcome?.revisions.find(
    (r) => r.result && r.sourceVersionRecordId === finding.versionRecordId,
  );
  const wasFixed = outcome?.fixed.some((f) => f.sourceFingerprint === fingerprint) ?? false;
  const stillReported =
    outcome?.remaining.some((f) => f.sourceFingerprint === fingerprint) ?? false;
  const skip = outcome?.skipped.find((s) => s.finding.sourceFingerprint === fingerprint);

  let body: React.ReactNode;
  if (!support.supported) {
    body = (
      <p className="lw-quiet" data-testid="detail-fix-unsupported">
        {support.reason}
      </p>
    );
  } else if (loading && !plan) {
    body = (
      <p className="lw-quiet" data-testid="detail-fix-loading">
        Checking for a deterministic fix…
      </p>
    );
  } else if (error) {
    body = (
      <p className="lw-quiet" data-testid="detail-fix-error">
        Fixes unavailable: {error}
      </p>
    );
  } else if (!entry) {
    body = (
      <p className="lw-quiet" data-testid="detail-fix-none">
        {NO_FIX_REASON}
      </p>
    );
  } else if (entry.status !== 'ready') {
    body = (
      <p className="lf-reason" data-testid="detail-fix-reason" data-status={entry.status}>
        {fixEntryReason(entry)}
      </p>
    );
  } else if (plan?.published) {
    body = (
      <Alert
        variant="neutral"
        icon={<Lock className="mt-px size-4 shrink-0" aria-hidden />}
        data-testid="detail-fix-published"
      >
        <span>
          <strong>Read-only.</strong> {PUBLISHED_REASON}
        </span>
      </Alert>
    );
  } else {
    body = (
      <p className="lw-quiet" data-testid="detail-fix-ready">
        A deterministic <span className="mono">{entry.fixClass}</span> fix is available
        {entry.wireVisible ? '; it changes what clients see on the wire' : ''}. Apply it as a new
        revision with <strong>Apply fix</strong>.
      </p>
    );
  }

  return (
    <section data-testid="detail-fix">
      <h3 className="hive-caps">Fix</h3>
      {revision?.result ? <LintFixResultNote result={revision.result} /> : null}
      {wasFixed ? (
        <p className="lw-quiet" data-testid="detail-fix-observed">
          The re-lint of the new revision no longer reports this finding, so it is marked{' '}
          <strong>Fixed</strong>.
        </p>
      ) : null}
      {stillReported ? (
        <p className="lf-reason" data-testid="detail-fix-still-reported">
          The re-lint of the new revision still reports this finding, so its state is unchanged.
        </p>
      ) : null}
      {skip ? (
        <p className="lf-reason" data-testid="detail-fix-skipped">
          Not applied: {skip.reason}
        </p>
      ) : null}
      {wasFixed ? null : body}
    </section>
  );
}
