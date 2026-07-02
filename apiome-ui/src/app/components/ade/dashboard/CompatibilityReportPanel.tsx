'use client';

import React from 'react';
import {
  groupCompatibilityFindings,
  type CompatibilityFindingRow,
} from '@lib/compatibility-report-group';

export type CompatibilityReportPanelProps = {
  overall?: string;
  findings: CompatibilityFindingRow[];
  ruleHits?: Record<string, number> | null;
  docUrl?: string | null;
  intro?: React.ReactNode;
  className?: string;
};

export function CompatibilityReportPanel({
  overall,
  findings,
  ruleHits,
  docUrl,
  intro,
  className = '',
}: CompatibilityReportPanelProps) {
  const grouped = React.useMemo(() => groupCompatibilityFindings(findings), [findings]);
  const ruleEntries = React.useMemo(() => {
    if (!ruleHits || typeof ruleHits !== 'object') {
      return [];
    }
    return Object.entries(ruleHits).sort(([a], [b]) => a.localeCompare(b));
  }, [ruleHits]);

  return (
    <div className={`space-y-3 text-xs ${className}`}>
      {intro ? <div className="text-gray-600 dark:text-gray-400">{intro}</div> : null}
      {overall ? (
        <p className="text-gray-700 dark:text-gray-300">
          <span className="font-medium">Overall:</span> {overall}
        </p>
      ) : null}
      {ruleEntries.length > 0 ? (
        <div className="rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 px-2 py-1.5">
          <p className="font-medium text-gray-800 dark:text-gray-200 mb-1">Rule hits</p>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-[11px] text-gray-600 dark:text-gray-400">
            {ruleEntries.map(([rule, n]) => (
              <li key={rule}>
                <span className="text-gray-800 dark:text-gray-200">{rule}</span>
                {' × '}
                {n}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {grouped.length === 0 ? (
        <p className="text-gray-500 dark:text-gray-400">No structural findings in this report.</p>
      ) : (
        <div className="space-y-3 max-h-64 overflow-y-auto pr-1">
          {grouped.map((section) => (
            <div key={section.severity}>
              <p className="font-medium text-gray-800 dark:text-gray-200 mb-1">{section.label}</p>
              <ul className="space-y-2 pl-0 list-none">
                {section.paths.map(({ path, findings: pathFindings }) => (
                  <li key={`${section.severity}-${path}`} className="border-l-2 border-gray-200 dark:border-gray-600 pl-2">
                    <div className="font-mono text-[11px] text-gray-700 dark:text-gray-300 break-all">{path}</div>
                    <ul className="mt-0.5 space-y-0.5 list-disc pl-4 text-gray-600 dark:text-gray-400">
                      {pathFindings.map((f) => (
                        <li key={f.id ?? `${f.path}-${f.rule}-${f.message}`}>
                          <span className="font-mono text-[10px] text-gray-500 dark:text-gray-500">{f.rule}</span>
                          {' — '}
                          {f.message}
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {docUrl ? (
        <a
          href={docUrl}
          target="_blank"
          rel="noreferrer"
          className="text-xs underline inline-block text-blue-600 dark:text-blue-400"
        >
          Breaking changes documentation (#746)
        </a>
      ) : null}
    </div>
  );
}
