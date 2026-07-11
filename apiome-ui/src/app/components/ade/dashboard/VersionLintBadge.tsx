'use client';

/**
 * Server-backed quality/lint badge for a single version (#3609).
 *
 * The grade shown here is computed by apiome-rest (`GET .../lint`) — the authoritative
 * source of truth, not client-side localStorage scoring. Clicking the badge opens the
 * per-version lint report (score, severity counts, itemized findings).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { LintReportDialog } from './LintReportDialog';
import {
  fetchVersionLintReport,
  gradeChipClass,
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

      <LintReportDialog
        open={open}
        onOpenChange={setOpen}
        title={`Quality & Lint report${versionLabel ? ` — v${versionLabel}` : ''}`}
        description="Server-computed quality score and itemized findings for this version."
        report={report}
        preferenceView="studio-lint"
      />
    </>
  );
}
