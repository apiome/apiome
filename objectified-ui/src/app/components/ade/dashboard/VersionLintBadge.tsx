'use client';

/**
 * Server-backed quality/lint badge for a single version (#3609).
 *
 * The grade shown here is computed by objectified-rest (`GET .../lint`) — the authoritative
 * source of truth, not client-side localStorage scoring. Clicking the badge opens the
 * per-version lint report (score, severity counts, itemized findings).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '../../ui/Dialog';
import {
  fetchVersionLintReport,
  gradeChipClass,
  severityBadgeClass,
  sortLintFindings,
  type VersionLintReport,
} from '../../../utils/version-lint-report';

interface VersionLintBadgeProps {
  projectId: string;
  versionId: string;
  /** Human-readable version label for the dialog title (e.g. "1.0.0"). */
  versionLabel?: string;
}

const chipBaseClass =
  'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500';

export function VersionLintBadge({ projectId, versionId, versionLabel }: VersionLintBadgeProps) {
  const [report, setReport] = useState<VersionLintReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const runFetch = useCallback(
    (controller: AbortController) =>
      fetchVersionLintReport(projectId, versionId, { signal: controller.signal })
        .then((r) => {
          if (!controller.signal.aborted) {
            setReport(r);
            setLoading(false);
          }
        })
        .catch((e: unknown) => {
          if (controller.signal.aborted) return;
          setError(e instanceof Error ? e.message : 'Failed to load lint report');
          setLoading(false);
        }),
    [projectId, versionId]
  );

  useEffect(() => {
    const controller = new AbortController();
    abortRef.current = controller;
    void runFetch(controller);
    return () => controller.abort();
  }, [runFetch]);

  // Retry from the error chip (event handler — safe to reset state synchronously).
  const retry = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    void runFetch(controller);
  }, [runFetch]);

  if (loading) {
    return (
      <span
        className={`${chipBaseClass} animate-pulse border-gray-200 bg-gray-100 text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400`}
        title="Loading quality score…"
        data-testid="version-lint-badge-loading"
      >
        Lint…
      </span>
    );
  }

  if (error || !report) {
    return (
      <button
        type="button"
        onClick={retry}
        className={`${chipBaseClass} border-gray-200 bg-gray-100 text-gray-500 hover:bg-gray-200 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700`}
        title={error ? `${error} — click to retry` : 'Quality score unavailable — click to retry'}
        data-testid="version-lint-badge-error"
      >
        Lint —
      </button>
    );
  }

  const findings = sortLintFindings(report.findings);
  const severity = report.severityCounts ?? {};

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`${chipBaseClass} ${gradeChipClass(report.grade)} hover:opacity-90`}
        title={`Quality score ${report.score}/100 — open lint report`}
        data-testid="version-lint-badge"
      >
        <ShieldCheck className="h-3 w-3" aria-hidden />
        {report.grade} · {report.score}
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              Quality &amp; Lint report{versionLabel ? ` — v${versionLabel}` : ''}
            </DialogTitle>
            <DialogDescription>
              Server-computed quality score and itemized findings for this version.
            </DialogDescription>
          </DialogHeader>

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
        </DialogContent>
      </Dialog>
    </>
  );
}
