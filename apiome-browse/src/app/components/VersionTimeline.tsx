'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { sanitizeSearchInput, SAFE_SEARCH_HTML_PATTERN } from '../utils/searchValidation';
import type { Severity } from '../../../lib/changelog/types';
import {
  severityBadgeClasses,
  severityDotClasses,
  severityLabel,
} from '../../../lib/changelog/group';

interface Version {
  id: string;
  version_id: string;
  description?: string;
  change_log?: string;
  published: boolean;
  published_at?: string;
  created_at?: string;
}

interface VersionTimelineProps {
  versions: Version[];
  /** Classified max severity per version label, when a stored changelog row exists (CTG-3.2). */
  changelogSeverities?: Record<string, Severity>;
  tenantSlug: string;
  projectSlug: string;
  latestVersionId?: string;
  searchable?: boolean;
}

function relativeTime(iso?: string): string | undefined {
  if (!iso) return undefined;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return undefined;
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.round(months / 12)}y ago`;
}

export function VersionTimeline({
  versions,
  changelogSeverities,
  tenantSlug,
  projectSlug,
  latestVersionId,
  searchable = false,
}: VersionTimelineProps) {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    if (!query.trim()) return versions;
    const q = query.toLowerCase();
    return versions.filter(
      (v) =>
        v.version_id.toLowerCase().includes(q) ||
        (v.description ?? '').toLowerCase().includes(q) ||
        (v.change_log ?? '').toLowerCase().includes(q)
    );
  }, [query, versions]);

  if (versions.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border-strong bg-surface/40 p-10 text-center">
        <p className="text-base text-fg-muted">
          No published versions available.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {searchable && (
        <div className="flex items-center gap-3">
          <div className="relative max-w-md flex-1">
            <svg
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.75}
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(sanitizeSearchInput(e.target.value))}
              pattern={SAFE_SEARCH_HTML_PATTERN}
              placeholder="Filter versions..."
              className="control pl-9 pr-3"
            />
          </div>
          <span className="text-xs text-fg-muted">
            {filtered.length} of {versions.length}
          </span>
        </div>
      )}

      <ol className="relative space-y-3 before:absolute before:left-[15px] before:top-1 before:bottom-1 before:w-px before:bg-inset">
        {filtered.map((v, idx) => {
          const isLatest = latestVersionId
            ? v.version_id === latestVersionId
            : idx === 0;
          return (
            <li key={v.id} className="relative pl-10">
              <div
                className={`absolute left-0 top-3 flex h-8 w-8 items-center justify-center rounded-full border-2 ${
                  isLatest
                    ? 'border-ok bg-ok-soft'
                    : 'border-border-strong bg-surface'
                }`}
                aria-hidden="true"
              >
                <span
                  className={`h-2 w-2 rounded-full ${
                    isLatest ? 'bg-ok' : 'bg-fg-faint'
                  }`}
                />
              </div>

              <Link
                href={`/tenant/${tenantSlug}/${projectSlug}/${v.version_id}`}
                className="group block rounded-lg border border-border bg-surface p-4 shadow-xs transition-all hover:-translate-y-0.5 hover:border-border-strong hover:shadow-md"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-lg font-semibold text-fg group-hover:text-accent-fg">
                        v{v.version_id}
                      </span>
                      {isLatest && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-ok-soft px-2 py-0.5 text-2xs font-medium text-ok-fg">
                          <span className="h-1.5 w-1.5 rounded-full bg-ok"></span>
                          Latest
                        </span>
                      )}
                      <span className="inline-flex items-center gap-1 rounded-full bg-subtle px-2 py-0.5 text-2xs font-medium text-fg-muted">
                        Published
                      </span>
                      {changelogSeverities?.[v.version_id] && (
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium ${severityBadgeClasses(changelogSeverities[v.version_id])}`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${severityDotClasses(changelogSeverities[v.version_id])}`}
                          ></span>
                          {severityLabel(changelogSeverities[v.version_id])}
                        </span>
                      )}
                    </div>
                    {v.description && (
                      <p className="mt-1 line-clamp-1 text-sm text-fg-muted">
                        {v.description}
                      </p>
                    )}
                  </div>
                  <div className="text-right text-xs text-fg-muted">
                    {v.published_at && (
                      <>
                        <div className="font-medium text-fg-muted">
                          {relativeTime(v.published_at)}
                        </div>
                        <div className="mt-0.5 tabular-nums">
                          {new Date(v.published_at).toLocaleDateString()}
                        </div>
                      </>
                    )}
                  </div>
                </div>

                {v.change_log && (
                  <div className="mt-3 rounded-md bg-subtle p-3">
                    <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-fg-muted">
                      Changelog
                    </div>
                    <p className="line-clamp-3 whitespace-pre-wrap text-sm leading-relaxed text-fg-muted">
                      {v.change_log}
                    </p>
                  </div>
                )}
              </Link>
            </li>
          );
        })}
      </ol>

      {searchable && query && filtered.length === 0 && (
        <div className="rounded-lg border border-dashed border-border-strong bg-surface/40 p-6 text-center text-base text-fg-muted">
          No versions match {`"${query}"`}.
        </div>
      )}
    </div>
  );
}
