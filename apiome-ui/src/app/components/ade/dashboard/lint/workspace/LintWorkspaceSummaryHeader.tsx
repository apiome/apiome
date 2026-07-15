'use client';

/**
 * Posture summary header for the lint workspace (CLX-4.1, #4859).
 *
 * The "can I trust the catalog?" strip: composite grade distribution, the two acceptance
 * callouts (unwaived security errors, subjects missing required coverage), waiver counts,
 * and per-axis assessed/not-assessed chips. Pure presentation — data arrives parsed via
 * lintWorkspaceSummaryFromPayload.
 */

import React from 'react';
import { gradeChipClass } from '@/app/utils/version-lint-report';
import type { LintWorkspaceSummary } from '@/app/utils/lint-workspace';
import { dashboardPanelPaddedClass } from '../../dashboardScreenClasses';
import { cn } from '@lib/utils';

const tileClass = `${dashboardPanelPaddedClass} flex flex-col gap-1`;
const tileLabelClass =
  'text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400';
const tileValueClass = 'text-2xl font-semibold text-gray-900 dark:text-gray-100';
const calloutAlertClass =
  'text-2xl font-semibold text-rose-600 dark:text-rose-400';
const calloutOkClass = 'text-2xl font-semibold text-emerald-600 dark:text-emerald-400';

export interface LintWorkspaceSummaryHeaderProps {
  summary: LintWorkspaceSummary;
  /** Jump the queue to the given canned filter (chips are buttons, not links). */
  onDrillDown?: (filter: 'security-errors' | 'new' | 'waiver-requests') => void;
}

/** Posture tiles + axis chips for the top of the workspace. */
export default function LintWorkspaceSummaryHeader({
  summary,
  onDrillDown,
}: LintWorkspaceSummaryHeaderProps) {
  const securityErrors = summary.findings.unwaived_security_errors ?? 0;
  const missingCoverage = summary.coverage.missingCount;
  const newCount = summary.findings.new_count ?? 0;
  const requested = summary.waivers.requested ?? 0;
  const subjectTotal =
    (summary.subjects.catalog_revisions ?? 0) + (summary.subjects.mcp_endpoint_versions ?? 0);

  return (
    <section data-testid="lint-workspace-summary" className="space-y-4">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <button
          type="button"
          data-testid="summary-security-errors"
          className={cn(tileClass, 'text-left', onDrillDown && 'cursor-pointer')}
          onClick={() => onDrillDown?.('security-errors')}
        >
          <span className={tileLabelClass}>Unwaived security errors</span>
          <span className={securityErrors > 0 ? calloutAlertClass : calloutOkClass}>
            {securityErrors}
          </span>
        </button>
        <div data-testid="summary-missing-coverage" className={tileClass}>
          <span className={tileLabelClass}>Missing required coverage</span>
          <span className={missingCoverage > 0 ? calloutAlertClass : calloutOkClass}>
            {missingCoverage}
          </span>
          <span className="text-xs text-gray-500 dark:text-gray-400">
            of {subjectTotal} subjects
          </span>
        </div>
        <button
          type="button"
          data-testid="summary-new-findings"
          className={cn(tileClass, 'text-left', onDrillDown && 'cursor-pointer')}
          onClick={() => onDrillDown?.('new')}
        >
          <span className={tileLabelClass}>New findings</span>
          <span className={tileValueClass}>{newCount}</span>
        </button>
        <button
          type="button"
          data-testid="summary-waivers"
          className={cn(tileClass, 'text-left', onDrillDown && 'cursor-pointer')}
          onClick={() => onDrillDown?.('waiver-requests')}
        >
          <span className={tileLabelClass}>Waivers</span>
          <span className={tileValueClass}>{summary.waivers.active ?? 0}</span>
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {requested} requested · {summary.waivers.expiring_soon ?? 0} expiring soon
          </span>
        </button>
      </div>

      <div className={cn(dashboardPanelPaddedClass, 'flex flex-wrap items-center gap-4')}>
        <div className="flex items-center gap-2" data-testid="summary-grades">
          <span className={tileLabelClass}>Grades</span>
          {Object.entries(summary.gradeDistribution)
            .filter(([, count]) => count > 0)
            .map(([grade, count]) => (
              <span
                key={grade}
                className={cn(
                  'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-semibold',
                  grade === 'ungraded'
                    ? 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
                    : gradeChipClass(grade),
                )}
              >
                {grade === 'ungraded' ? 'Ungraded' : grade}
                <span className="font-normal">{count}</span>
              </span>
            ))}
        </div>
        <div className="flex flex-wrap items-center gap-2" data-testid="summary-axes">
          <span className={tileLabelClass}>Axes</span>
          {summary.axes.map((axis) => (
            <span
              key={axis.key}
              title={
                axis.assessedCount
                  ? `${axis.label}: ${axis.assessedCount} assessed, ${axis.notAssessedCount} not assessed`
                  : `${axis.label}: not assessed anywhere`
              }
              className={cn(
                'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium',
                axis.assessedCount > 0
                  ? 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300'
                  : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
              )}
            >
              {axis.label}
              <span className="font-normal">
                {axis.averageScore !== null ? axis.averageScore : '—'}
              </span>
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
