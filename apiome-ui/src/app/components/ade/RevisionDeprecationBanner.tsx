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
      className={`flex gap-3 border-b border-warn/80 bg-warn-soft px-4 py-2.5 text-sm text-warn-fg ${className}`}
    >
      <AlertTriangle className="h-5 w-5 shrink-0 text-warn-fg" aria-hidden />
      <div className="min-w-0 space-y-1">
        <p className="font-medium">
          Deprecated revision ({roleLabel}): {versionLabel}
        </p>
        <ul className="list-disc space-y-0.5 pl-4 text-warn-fg/90">
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
                        className="font-medium text-warn-fg underline underline-offset-2 hover:text-warn-fg"
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
