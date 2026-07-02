'use client';

import { GitBranch } from 'lucide-react';
import { buildLineageSnippet, branchNamesForTip, type VersionLineageInput } from './version-lineage';

export type VersionLineageSnippetProps = {
  /** Selected source revision id (copy-from). */
  sourceVersionId: string;
  versions: VersionLineageInput[];
  versionBranches: Array<{ name: string; tip_version_id: string }>;
  /** When set, shown as primary branch context (not color-only). */
  explicitBranchName?: string | null;
  isLoading?: boolean;
  /** No tenant / empty project */
  permissionDenied?: boolean;
};

export default function VersionLineageSnippet({
  sourceVersionId,
  versions,
  versionBranches,
  explicitBranchName,
  isLoading = false,
  permissionDenied = false,
}: VersionLineageSnippetProps) {
  if (permissionDenied) {
    return (
      <div
        role="status"
        className="rounded-md border border-dashed border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100"
      >
        You do not have access to load branch metadata for this project. You can still create a version if your role allows it.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div role="status" className="text-sm text-gray-500 dark:text-gray-400" aria-live="polite">
        Loading revision context…
      </div>
    );
  }

  const namesAtTip = branchNamesForTip(sourceVersionId, versionBranches);
  const branchLabel =
    explicitBranchName && explicitBranchName.trim().length > 0
      ? explicitBranchName.trim()
      : namesAtTip.length > 0
        ? namesAtTip.join(', ')
        : null;

  const model = buildLineageSnippet(sourceVersionId, versions, {
    branchNamesAtTip: namesAtTip.length > 0 ? namesAtTip : undefined,
  });

  if (!model) {
    return (
      <div
        role="status"
        className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-600 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-300"
      >
        Revision lineage could not be resolved (missing parent links in this project).
      </div>
    );
  }

  return (
    <div
      className="rounded-md border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900/30 px-3 py-3 space-y-2"
      aria-labelledby="create-copy-lineage-heading"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="create-copy-lineage-heading" className="text-xs font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400">
          Branch context
        </h3>
        {branchLabel && (
          <span className="inline-flex items-center gap-1 rounded border border-gray-300 bg-white px-2 py-0.5 text-xs font-medium text-gray-800 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100">
            <GitBranch className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>{branchLabel}</span>
          </span>
        )}
      </div>

      <p className="sr-only">{model.screenSummary}</p>

      <nav aria-label="Source revision chain" className="text-sm text-gray-800 dark:text-gray-200">
        <ol className="flex flex-wrap items-center gap-1 list-none p-0 m-0">
          {model.breadcrumbLabels.map((label, i) => (
            <li key={`${model.revisionIds[i]}-${i}`} className="flex items-center gap-1">
              {i > 0 && <span className="text-gray-400 select-none" aria-hidden="true">→</span>}
              <span
                className={
                  i === model.breadcrumbLabels.length - 1
                    ? 'font-semibold text-gray-900 dark:text-gray-50'
                    : ''
                }
              >
                {label}
                {i === model.breadcrumbLabels.length - 1 ? (
                  <span className="ml-1 text-xs font-normal text-gray-500 dark:text-gray-400">(source)</span>
                ) : null}
              </span>
            </li>
          ))}
        </ol>
      </nav>

      {model.mergeParentLabel ? (
        <p className="text-xs text-gray-600 dark:text-gray-400 border-l-2 border-gray-300 dark:border-gray-600 pl-2">
          <span className="font-medium text-gray-800 dark:text-gray-200">Merge:</span> includes {model.mergeParentLabel}
        </p>
      ) : null}

      {model.asciiLines.length > 0 && (
        <pre
          className="text-xs leading-relaxed text-gray-700 dark:text-gray-300 font-mono overflow-x-auto border-t border-gray-200 dark:border-gray-700 pt-2 mt-1"
          aria-hidden="true"
        >
          {model.asciiLines.join('\n')}
        </pre>
      )}
    </div>
  );
}
