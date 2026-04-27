'use client';

import { useCallback, useEffect, useId, useState } from 'react';
import Link from 'next/link';
import {
  AlertTriangle,
  ChevronRight,
  Clock,
  ExternalLink,
  Loader2,
  XCircle,
} from 'lucide-react';
import { formatRelativeTime } from '@/app/ade/dashboard/versions/version-history-dag';
import { dashboardPanelClass, repositoryActivityRowClass } from '@/app/components/ade/dashboard/dashboardScreenClasses';
import { Skeleton } from '@/app/components/ui/Skeleton';
import { Button } from '@/app/components/ui/Button';
import { cn } from '@lib/utils';

const ALL_IMPORTS_HREF = '/ade/dashboard/repositories';

type AttentionRow = {
  importJobId: string;
  repositoryId: string;
  repositoryFullName: string;
  projectName: string;
  versionLabel: string;
  state: string;
  reasonKind: string;
  primaryReason: string;
  createdAt: string;
  changeReportPath: string;
};

type AttentionResponse = {
  items: AttentionRow[];
  refreshedAt: string;
};

function statusBadgeClass(kind: string, state: string) {
  if (state === 'failed' || kind === 'failed') {
    return 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200';
  }
  if (state === 'pending_review' || kind === 'pending_review') {
    return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200';
  }
  return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200';
}

export function RecentImportsAttentionWidget() {
  const [data, setData] = useState<AttentionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dismissingId, setDismissingId] = useState<string | null>(null);
  const listId = useId();

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoadError(null);
    try {
      const res = await fetch('/api/dashboard/recent-imports-attention?limit=5', {
        signal,
        cache: 'no-store',
      });
      const j = (await res.json().catch(() => ({}))) as {
        success?: boolean;
        data?: AttentionResponse;
        error?: string;
      };
      if (signal?.aborted) return;
      if (!res.ok || j.success === false) {
        setData(null);
        setLoadError(j.error || 'Failed to load recent imports');
        return;
      }
      if (j.data) {
        setData(j.data);
      } else {
        setData({ items: [], refreshedAt: '' });
      }
    } catch (e) {
      if (signal?.aborted) return;
      setData(null);
      setLoadError(e instanceof Error ? e.message : 'Failed to load');
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const c = new AbortController();
    void load(c.signal);
    return () => c.abort();
  }, [load]);

  const onDismiss = async (importJobId: string) => {
    setDismissingId(importJobId);
    try {
      const res = await fetch('/api/dashboard/recent-imports-attention', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ importJobId }),
      });
      const j = (await res.json().catch(() => ({}))) as { success?: boolean; error?: string };
      if (!res.ok || j.success === false) {
        setLoadError(j.error || 'Could not dismiss');
        return;
      }
      setData((prev) =>
        prev
          ? { ...prev, items: prev.items.filter((r) => r.importJobId !== importJobId) }
          : prev
      );
    } finally {
      setDismissingId(null);
    }
  };

  const hasRows = (data?.items.length ?? 0) > 0;
  const emptyOk = !loadError && !loading && data && !hasRows;

  return (
    <div className={cn(dashboardPanelClass, 'overflow-hidden')}>
      <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 shrink-0 text-amber-500 dark:text-amber-400" />
              <h3
                className="text-base font-semibold text-gray-900 dark:text-white leading-snug"
                id={listId}
              >
                Recent Imports Needing Attention
              </h3>
            </div>
          </div>
          <Link
            href={ALL_IMPORTS_HREF}
            className="shrink-0 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:underline inline-flex items-center gap-1"
          >
            All imports
            <ExternalLink className="h-4 w-4" />
          </Link>
        </div>
      </div>
      <div>
        {loading && (
          <div className="p-4 space-y-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-2 py-2">
                <Skeleton className="h-4 w-2/5 max-w-xs" />
                <Skeleton className="h-5 w-20 rounded-md" />
                <Skeleton className="h-4 w-8" />
                <Skeleton className="h-4 w-12 ml-auto" />
              </div>
            ))}
          </div>
        )}
        {!loading && loadError && (
          <p className="p-4 text-sm text-rose-600 dark:text-rose-400" role="alert">
            {loadError}
          </p>
        )}
        {emptyOk && (
          <div className="text-center py-10 px-4">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-slate-100 to-gray-100 dark:from-slate-800/40 dark:to-gray-900/40 flex items-center justify-center mx-auto mb-4">
              <XCircle className="h-8 w-8 text-slate-500 dark:text-slate-400" />
            </div>
            <p className="text-sm font-medium text-gray-800 dark:text-gray-100">
              No repository imports need attention right now.
            </p>
          </div>
        )}
        {hasRows && !loading && data && (
          <ul
            className="divide-y divide-gray-100 dark:divide-gray-800"
            role="list"
            aria-labelledby={listId}
          >
            {data.items.map((row) => {
              const rel = formatRelativeTime(row.createdAt);
              const busy = dismissingId === row.importJobId;
              return (
                <li key={row.importJobId} className={cn(repositoryActivityRowClass, 'items-start gap-2 py-2')}>
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-2">
                    <Link
                      href={row.changeReportPath}
                      className="group flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 rounded-md px-2 py-1 hover:bg-gray-50 dark:hover:bg-gray-800/60 transition-colors"
                    >
                      <span
                        className="min-w-0 font-medium text-sm text-gray-900 dark:text-white"
                        title={`${row.repositoryFullName}`}
                      >
                        {row.projectName}
                        <span className="text-gray-400 dark:text-gray-500 font-normal"> · </span>
                        <span className="font-mono text-xs text-gray-600 dark:text-gray-300">
                          {row.versionLabel}
                        </span>
                      </span>
                      <span
                        className={cn(
                          'shrink-0 inline-flex max-w-full items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium',
                          statusBadgeClass(row.reasonKind, row.state)
                        )}
                      >
                        <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden />
                        <span className="truncate">{row.primaryReason}</span>
                      </span>
                      <span
                        className="shrink-0 text-xs text-gray-400 dark:text-gray-500 tabular-nums inline-flex items-center gap-0.5"
                        title="Created"
                      >
                        <Clock className="h-3.5 w-3.5" aria-hidden />
                        {rel || '—'}
                      </span>
                      <span
                        className="shrink-0 text-gray-400 group-hover:text-indigo-500 dark:group-hover:text-indigo-400"
                        aria-hidden
                      >
                        <ChevronRight className="h-4 w-4" />
                      </span>
                    </Link>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="shrink-0 text-xs h-8"
                      disabled={busy}
                      onClick={() => void onDismiss(row.importJobId)}
                    >
                      {busy ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                      ) : (
                        'Mark as reviewed'
                      )}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
