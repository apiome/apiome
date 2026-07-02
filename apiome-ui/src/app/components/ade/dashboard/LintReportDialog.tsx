'use client';

/**
 * Presentational dialog for a server-computed lint report (#3609, MFI-23.10).
 *
 * Extracted from {@link VersionLintBadge} so the per-version badge and the Catalog card/detail lint
 * orbs render the *identical* report surface (score + A-F grade, severity counts, optional
 * stale-score note, and the itemized findings table). The component is purely presentational: the
 * caller owns fetching and passes the `report` (plus optional `loading`/`error`/`onRetry` for the
 * lazily-fetched catalog case). The grade/score are the authoritative values computed by
 * apiome-rest — this component never recomputes them.
 */

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '../../ui/Dialog';
import {
  gradeChipClass,
  severityBadgeClass,
  sortLintFindings,
  type VersionLintReport,
} from '../../../utils/version-lint-report';

interface LintReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Dialog title (e.g. "Quality & Lint report — v1.0.0"). */
  title: string;
  /** Optional sub-line under the title. */
  description?: string;
  /** The server lint report, or null while loading / on error. */
  report: VersionLintReport | null;
  /** True while the report is being fetched (catalog lazy-fetch). */
  loading?: boolean;
  /** A fetch error message, when the report could not be loaded. */
  error?: string | null;
  /** Retry handler shown alongside an error, when provided. */
  onRetry?: () => void;
}

/**
 * Render a server lint report inside a dialog. Shows a loading line, an error + retry affordance, or
 * the score header and itemized findings table depending on the caller's fetch state.
 */
export function LintReportDialog({
  open,
  onOpenChange,
  title,
  description,
  report,
  loading = false,
  error = null,
  onRetry,
}: LintReportDialogProps) {
  const findings = report ? sortLintFindings(report.findings) : [];
  const severity = report?.severityCounts ?? {};

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>

        {loading ? (
          <p
            className="py-8 text-center text-sm text-gray-500 dark:text-gray-400"
            data-testid="lint-report-loading"
          >
            Loading lint report…
          </p>
        ) : error || !report ? (
          <div
            className="flex flex-col items-center gap-3 py-8 text-center"
            data-testid="lint-report-error"
          >
            <p className="text-sm text-gray-600 dark:text-gray-300">
              {error || 'Lint report unavailable.'}
            </p>
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
              >
                Retry
              </button>
            ) : null}
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <span
                className={`inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-lg font-bold ${gradeChipClass(
                  report.grade
                )}`}
              >
                {report.grade}
              </span>
              <span className="text-sm text-gray-600 dark:text-gray-300">
                Score <span className="font-semibold">{report.score}</span>/100
              </span>
              <span className="flex items-center gap-2 text-xs">
                <span className={`rounded px-1.5 py-0.5 ${severityBadgeClass('error')}`}>
                  {severity.error ?? 0} error
                </span>
                <span className={`rounded px-1.5 py-0.5 ${severityBadgeClass('warning')}`}>
                  {severity.warning ?? 0} warning
                </span>
                <span className={`rounded px-1.5 py-0.5 ${severityBadgeClass('info')}`}>
                  {severity.info ?? 0} info
                </span>
              </span>
              {report.compatibilityOverall && (
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  Compatibility vs base: {report.compatibilityOverall}
                </span>
              )}
            </div>

            {report.scoreIsStale && (
              <p
                className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
                data-testid="version-lint-stale-note"
              >
                The stored quality score
                {report.capturedGrade && report.capturedScore != null
                  ? ` (${report.capturedGrade} · ${report.capturedScore})`
                  : ''}{' '}
                is out of date — this report was recomputed from the current revision.
              </p>
            )}

            <div className="mt-3 max-h-[50vh] overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-700">
              {findings.length === 0 ? (
                <p className="p-4 text-sm text-gray-600 dark:text-gray-300">
                  No findings — clean bill of health.
                </p>
              ) : (
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50 text-left text-xs uppercase tracking-wider text-gray-500 dark:bg-gray-900/40 dark:text-gray-400">
                    <tr>
                      <th className="px-3 py-2">Severity</th>
                      <th className="px-3 py-2">Rule</th>
                      <th className="px-3 py-2">Path</th>
                      <th className="px-3 py-2">Message</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {findings.map((f) => (
                      <tr key={f.id}>
                        <td className="px-3 py-2 align-top">
                          <span className={`rounded px-1.5 py-0.5 text-xs ${severityBadgeClass(f.severity)}`}>
                            {f.severity}
                          </span>
                        </td>
                        <td className="px-3 py-2 align-top font-mono text-xs text-gray-700 dark:text-gray-300">
                          {f.rule}
                        </td>
                        <td className="px-3 py-2 align-top font-mono text-xs text-gray-500 dark:text-gray-400">
                          {f.path}
                        </td>
                        <td className="px-3 py-2 align-top text-gray-700 dark:text-gray-200">{f.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
