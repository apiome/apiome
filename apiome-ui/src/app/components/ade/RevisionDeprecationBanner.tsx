'use client';

import * as React from 'react';
import { AlertTriangle } from 'lucide-react';
import { revisionDeprecationLines } from '@/app/utils/revision-deprecation';

export interface RevisionDeprecationBannerProps {
  /** Role label shown in the banner title */
  roleLabel: string;
  /** Semantic version string (e.g. 1.0.0) */
  versionLabel: string;
  metadata: unknown;
  className?: string;
}

/**
 * Warning strip when a schema revision is marked deprecated in versions.metadata.
 */
export default function RevisionDeprecationBanner({
  roleLabel,
  versionLabel,
  metadata,
  className = '',
}: RevisionDeprecationBannerProps) {
  const lines = revisionDeprecationLines(metadata);
  if (lines.length === 0) return null;

  return (
    <div
      role="status"
      className={`flex gap-3 border-b border-amber-300/80 bg-amber-50 px-4 py-2.5 text-sm text-amber-950 dark:border-amber-700/80 dark:bg-amber-950/40 dark:text-amber-100 ${className}`}
    >
      <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
      <div className="min-w-0 space-y-1">
        <p className="font-medium">
          Deprecated revision ({roleLabel}): {versionLabel}
        </p>
        <ul className="list-disc space-y-0.5 pl-4 text-amber-900/90 dark:text-amber-100/90">
          {lines.map((line, i) => (
            <li key={i} className="break-words">
              {line.includes('https://') ? (
                <>
                  {line.split(/(https:\/\/[^\s]+)/g).map((part, j) =>
                    part.startsWith('https://') ? (
                      <a
                        key={j}
                        href={part}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-amber-800 underline underline-offset-2 hover:text-amber-950 dark:text-amber-200 dark:hover:text-white"
                      >
                        {part}
                      </a>
                    ) : (
                      <span key={j}>{part}</span>
                    )
                  )}
                </>
              ) : (
                line
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
