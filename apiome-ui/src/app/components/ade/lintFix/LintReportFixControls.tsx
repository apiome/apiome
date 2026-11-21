'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowUpRight, Lock, Wrench } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  PUBLISHED_REASON,
  fixEntryForFinding,
  fixEntryReason,
  readyFixIds,
  revisionHref,
  type LintFixApplyResult,
  type LintFixEntry,
} from '@/app/utils/lint-fix';

import type { RevisionLintFixes } from './useRevisionLintFixes';

/**
 * The Lint report dialog's fix controls — GVM-3.6 (#5874).
 *
 * Two pieces the dialog places: {@link LintReportFixBar} above the findings (the *Apply N
 * deterministic fixes* button, the published read-only note, the apply result and refusal), and
 * {@link LintFixRowAction} on each finding (the *Fix* chip of a ready fix, or the reason a
 * `breaking` / `conflict` / `excluded` fix is not applied). Both only render state; the dialog
 * owns the confirm-with-reason step.
 */

/** A request to apply: the fixes, and the rule when there is exactly one. */
export interface LintFixApplyRequest {
  fixIds: string[];
  ruleId: string | null;
}

/**
 * The link to the revision an apply created, with its score.
 *
 * @param props.result The created revision.
 * @returns The success note.
 */
export function LintFixResultNote({ result }: { result: LintFixApplyResult }) {
  const count = result.appliedFixIds.length;
  return (
    <Alert variant="ok" data-testid="lint-fix-result">
      <span>
        Applied {count} fix{count === 1 ? '' : 'es'} as a new revision{' '}
        <Link
          href={revisionHref(result.projectId)}
          className="lf-link mono"
          data-testid="lint-fix-result-link"
        >
          v{result.versionLabel}
          <ArrowUpRight aria-hidden />
        </Link>
        {result.grade && result.score != null
          ? ` — re-linted: ${result.grade} · ${result.score}/100.`
          : '.'}
      </span>
    </Alert>
  );
}

/** Props for {@link LintReportFixBar}. */
export interface LintReportFixBarProps {
  fixes: RevisionLintFixes;
  onRequestApply: (request: LintFixApplyRequest) => void;
}

/**
 * The bar above the findings.
 *
 * @param props See {@link LintReportFixBarProps}.
 * @returns The bar, or nothing when the plan has no entries and nothing happened.
 */
export function LintReportFixBar({ fixes, onRequestApply }: LintReportFixBarProps) {
  const { plan, loading, error, busy, result, applyError } = fixes;
  const ready = readyFixIds(plan);

  if (loading && !plan) {
    return (
      <p className="hive-quiet" data-testid="lint-fix-plan-loading">
        Checking for deterministic fixes…
      </p>
    );
  }

  return (
    <div className="lf-bar" data-testid="lint-fix-bar">
      {result ? <LintFixResultNote result={result} /> : null}
      {applyError ? (
        <Alert variant="error" data-testid="lint-fix-apply-error">
          {applyError}
        </Alert>
      ) : null}
      {error ? (
        <p className="hive-quiet" data-testid="lint-fix-plan-error">
          Fixes unavailable: {error}
        </p>
      ) : null}
      {plan?.published && plan.entries.length > 0 ? (
        <Alert
          variant="neutral"
          icon={<Lock className="mt-px size-4 shrink-0" aria-hidden />}
          data-testid="lint-fix-published"
        >
          <span>
            <strong>Fixes are read-only.</strong> {PUBLISHED_REASON}
          </span>
        </Alert>
      ) : null}
      {plan && !plan.published && ready.length > 0 ? (
        <div className="lf-bar__row">
          <span className="hive-quiet">
            {ready.length} finding{ready.length === 1 ? ' has' : 's have'} a deterministic fix.
          </span>
          <Button
            size="sm"
            disabled={busy}
            title={busy ? 'Fixes are being applied.' : 'Apply every ready fix as one new revision'}
            data-testid="lint-fix-apply-all"
            onClick={() => onRequestApply({ fixIds: ready, ruleId: null })}
          >
            <Wrench aria-hidden />
            Apply {ready.length} deterministic fix{ready.length === 1 ? '' : 'es'}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** Props for {@link LintFixRowAction}. */
export interface LintFixRowActionProps {
  fixes: RevisionLintFixes;
  /** The finding the row draws. */
  finding: { id: string; rule: string; path: string };
  onRequestApply: (request: LintFixApplyRequest) => void;
}

/**
 * The fix affordance of one finding row.
 *
 * @param props See {@link LintFixRowActionProps}.
 * @returns The chip and/or reason, or nothing for a finding without a fix.
 */
export function LintFixRowAction({ fixes, finding, onRequestApply }: LintFixRowActionProps) {
  const entry: LintFixEntry | null = fixEntryForFinding(fixes.plan, finding);
  if (!entry) return null;
  const reason = fixEntryReason(entry);
  const published = fixes.plan?.published === true;

  if (entry.status === 'ready') {
    return published ? (
      <div className="lf-row" data-testid="lint-fix-row" data-status="read-only">
        <Badge variant="outline" title={PUBLISHED_REASON} data-testid="lint-fix-chip-readonly">
          <Lock aria-hidden />
          Fix
        </Badge>
        <span className="hive-quiet">{PUBLISHED_REASON}</span>
      </div>
    ) : (
      <div className="lf-row" data-testid="lint-fix-row" data-status="ready">
        <button
          type="button"
          className="lf-chip"
          disabled={fixes.busy}
          title={`Apply the ${entry.ruleId} fix as a new revision`}
          aria-label={`Fix: ${entry.ruleId} at ${entry.path || 'document'}`}
          data-testid="lint-fix-chip"
          onClick={() => onRequestApply({ fixIds: [entry.fixId], ruleId: entry.ruleId })}
        >
          <Wrench aria-hidden />
          Fix
        </button>
        {entry.wireVisible ? (
          <span className="hive-quiet">Changes what clients see on the wire.</span>
        ) : null}
      </div>
    );
  }

  return (
    <div className="lf-row" data-testid="lint-fix-row" data-status={entry.status}>
      <Badge
        status={entry.status === 'breaking' ? 'warning' : 'info'}
        data-testid="lint-fix-status"
      >
        {entry.status === 'breaking'
          ? 'Breaking fix'
          : entry.status === 'conflict'
            ? 'Conflicting fix'
            : 'Fix not in plan'}
      </Badge>
      <span className="lf-reason" data-testid="lint-fix-reason-text">
        {reason}
      </span>
    </div>
  );
}
