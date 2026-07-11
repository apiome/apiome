'use client';

/**
 * SchemaVersionScoringPanel — Studio lint panel (GOV-2.4, #4436).
 *
 * The Designer/Studio surface for server-computed quality scoring: grade chip, applied style guide,
 * and itemized violations with rule id, rationale, guide name, and docs links. Also embedded in the
 * post-import report so developers see governance context immediately after import.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { cn } from '@lib/utils';
import { dashboardPanelClass } from '@/app/components/ade/dashboard/dashboardScreenClasses';
import {
  fetchVersionLintReport,
  gradeChipClass,
  type VersionLintReport,
} from '@/app/utils/version-lint-report';
import type { LintViolationDisplayView } from '@/app/utils/lint-violation-display-preferences';
import {
  LintViolationFindingsList,
  lintReportGuideContext,
} from './lint/LintViolationFindingsList';

type PanelStatus = 'idle' | 'loading' | 'loaded' | 'error';

export interface SchemaVersionScoringPanelProps {
  projectId: string;
  versionId: string;
  /** Human-readable version label for the header. */
  versionLabel?: string;
  className?: string;
  /** When false, defer fetching until activated (mirrors catalog lazy tab). */
  active?: boolean;
  /** Which surface's group-by-rule preference to persist (defaults to Studio). */
  preferenceView?: LintViolationDisplayView;
}

/**
 * Fetch and render the authoritative lint report for one project version (Studio / import report).
 */
export function SchemaVersionScoringPanel({
  projectId,
  versionId,
  versionLabel,
  className,
  active = true,
  preferenceView = 'studio-lint',
}: SchemaVersionScoringPanelProps) {
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [report, setReport] = useState<VersionLintReport | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fetchStartedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const loadReport = useCallback(async () => {
    if (!active || fetchStartedRef.current) return;
    fetchStartedRef.current = true;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus('loading');
    setErrorMessage(null);
    let loaded: VersionLintReport | null = null;
    let failure: string | null = null;
    try {
      loaded = await fetchVersionLintReport(projectId, versionId, { signal: controller.signal });
    } catch (e) {
      failure = e instanceof Error ? e.message : 'Failed to load lint report.';
    } finally {
      if (controller.signal.aborted) {
        /* superseded */
      } else if (failure != null) {
        setErrorMessage(failure);
        setStatus('error');
      } else {
        setReport(loaded);
        setStatus('loaded');
      }
    }
  }, [active, projectId, versionId]);

  useEffect(() => {
    void loadReport();
  }, [loadReport]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const retry = useCallback(() => {
    fetchStartedRef.current = false;
    void loadReport();
  }, [loadReport]);

  const guide = lintReportGuideContext(report);

  return (
    <section
      className={cn(dashboardPanelClass, 'p-6', className)}
      data-testid="schema-version-scoring-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
          Lint &amp; score
          {versionLabel ? (
            <span className="ml-2 font-mono normal-case text-gray-700 dark:text-gray-300">
              v{versionLabel}
            </span>
          ) : null}
        </h2>
        {report?.guideName ? (
          <span
            data-testid="studio-lint-guide-name"
            className="rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-200"
          >
            Guide: {report.guideName}
          </span>
        ) : null}
      </div>

      {status === 'idle' || status === 'loading' ? (
        <p className="mt-4 text-sm text-gray-500 dark:text-gray-400" data-testid="studio-lint-loading">
          Loading lint report…
        </p>
      ) : status === 'error' ? (
        <div
          className="mt-4 flex flex-col items-start gap-3 rounded-xl border border-rose-200 bg-rose-50/60 p-4 text-sm dark:border-rose-900 dark:bg-rose-950/30"
          data-testid="studio-lint-error"
        >
          <span className="flex items-center gap-2 text-rose-700 dark:text-rose-300">
            <AlertCircle className="h-4 w-4 shrink-0" aria-hidden />
            {errorMessage || 'Failed to load lint report.'}
          </span>
          <button
            type="button"
            data-testid="studio-lint-retry"
            onClick={retry}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
          >
            <RefreshCw className="h-4 w-4" /> Retry
          </button>
        </div>
      ) : report ? (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <span
              className={`inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-lg font-bold ${gradeChipClass(report.grade)}`}
              data-testid="studio-lint-grade"
            >
              {report.grade}
            </span>
            <span className="text-sm text-gray-600 dark:text-gray-300">
              Score <span className="font-semibold">{report.score}</span>/100
            </span>
          </div>

          <div className="mt-4">
            <LintViolationFindingsList
              findings={report.findings}
              guideName={guide.guideName}
              guideId={guide.guideId}
              preferenceView={preferenceView}
            />
          </div>
        </>
      ) : null}
    </section>
  );
}

export default SchemaVersionScoringPanel;
