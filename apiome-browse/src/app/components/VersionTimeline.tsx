'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { sanitizeSearchInput, SAFE_SEARCH_HTML_PATTERN } from '../utils/searchValidation';

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
      <div className="rounded-xl border border-dashed border-zinc-300 bg-white/40 p-10 text-center dark:border-zinc-700 dark:bg-zinc-900/40">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
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
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400"
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
              className="h-9 w-full rounded-md border border-zinc-200 bg-white pl-9 pr-3 text-sm text-zinc-900 placeholder-zinc-400 shadow-xs transition-colors focus-visible:border-[var(--brand)] focus-visible:outline-none dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder-zinc-500"
            />
          </div>
          <span className="text-xs text-zinc-500 dark:text-zinc-400">
            {filtered.length} of {versions.length}
          </span>
        </div>
      )}

      <ol className="relative space-y-3 before:absolute before:left-[15px] before:top-1 before:bottom-1 before:w-px before:bg-zinc-200 before:dark:bg-zinc-800">
        {filtered.map((v, idx) => {
          const isLatest = latestVersionId
            ? v.version_id === latestVersionId
            : idx === 0;
          return (
            <li key={v.id} className="relative pl-10">
              <div
                className={`absolute left-0 top-3 flex h-8 w-8 items-center justify-center rounded-full border-2 ${
                  isLatest
                    ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-500/10'
                    : 'border-zinc-300 bg-white dark:border-zinc-700 dark:bg-zinc-950'
                }`}
                aria-hidden="true"
              >
                <span
                  className={`h-2 w-2 rounded-full ${
                    isLatest ? 'bg-emerald-500' : 'bg-zinc-400 dark:bg-zinc-600'
                  }`}
                />
              </div>

              <Link
                href={`/tenant/${tenantSlug}/${projectSlug}/${v.version_id}`}
                className="group block rounded-xl border border-zinc-200 bg-white p-4 shadow-xs transition-all hover:-translate-y-0.5 hover:border-zinc-300 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-zinc-700"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[15px] font-semibold text-zinc-900 group-hover:text-[var(--brand)] dark:text-zinc-50">
                        v{v.version_id}
                      </span>
                      {isLatest && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                          Latest
                        </span>
                      )}
                      <span className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                        Published
                      </span>
                    </div>
                    {v.description && (
                      <p className="mt-1 line-clamp-1 text-[13px] text-zinc-600 dark:text-zinc-400">
                        {v.description}
                      </p>
                    )}
                  </div>
                  <div className="text-right text-xs text-zinc-500 dark:text-zinc-400">
                    {v.published_at && (
                      <>
                        <div className="font-medium text-zinc-700 dark:text-zinc-300">
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
                  <div className="mt-3 rounded-md bg-zinc-50 p-3 dark:bg-zinc-900/60">
                    <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                      Changelog
                    </div>
                    <p className="line-clamp-3 whitespace-pre-wrap text-[13px] leading-relaxed text-zinc-700 dark:text-zinc-300">
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
        <div className="rounded-xl border border-dashed border-zinc-300 bg-white/40 p-6 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900/40 dark:text-zinc-500">
          No versions match {`"${query}"`}.
        </div>
      )}
    </div>
  );
}
