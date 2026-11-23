'use client';

/**
 * Compact paginated recent-jobs table (IXH-6.3, #5122).
 *
 * Consumes the BFF list proxies (`GET /api/export/jobs` or `GET /api/catalog/import`)
 * one page at a time — never fetches the unbounded full history. The lists page by cursor
 * (DBP-1.13, #7196): Next continues from the page's `next_cursor`, Previous returns to a cursor
 * already used, and only the first page asks for the count.
 *
 * Re-skinned by HIVE-6.4 (#5315) onto `DataTable`, which is what the import wizard's *Recent
 * import jobs* drawer needed anyway: the table brings the caps header, the dense rows, the
 * loading placeholders, the empty state and the failure state that this had hand-rolled or
 * lacked. The pager stays the two buttons: a cursor says whether another page follows, not how
 * many there are, which is what `DataTablePager` wants.
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  EMPTY_PAGE_INFO,
  cursorRangeLabel,
  hasMoreAfter,
  readPage,
  setPageParams,
  type PageInfo,
  type PageRequest,
} from '@lib/cursor-pages';
import { useCursorTrail } from '@/app/hooks/useCursorPages';
import { Badge } from '../../../ui/Badge';
import { Button } from '../../../ui/Button';
import {
  DataTable,
  DataTableFoot,
  type DataTableColumn,
} from '../../../ui/DataTable';
import { EmptyState } from '../../../ui/EmptyState';

const DEFAULT_LIMIT = 10;

export type RecentAsyncJobKind = 'export' | 'import';

export interface RecentAsyncJobRow {
  job_id: string;
  state: string;
  percent?: number;
  artifact?: string | null;
  target?: string | null;
}

interface ListPayload {
  jobs?: RecentAsyncJobRow[];
  total?: number | null;
  limit?: number;
  offset?: number;
  has_more?: boolean;
  next_cursor?: string | null;
  success?: boolean;
  error?: string;
}

export interface RecentAsyncJobsPanelProps {
  kind: RecentAsyncJobKind;
  /** Page size (default 10). */
  limit?: number;
  title?: string;
  className?: string;
  /** Optional test id prefix (defaults from kind). */
  testId?: string;
}

/**
 * The BFF list URL for one page of recent jobs.
 *
 * @param kind Which job store.
 * @param limit Page size.
 * @param page Where the page starts (the previous page's cursor) and whether to count the jobs.
 * @returns The relative URL.
 */
export function recentAsyncJobsUrl(
  kind: RecentAsyncJobKind,
  limit: number,
  page: PageRequest = {}
): string {
  const base = kind === 'export' ? '/api/export/jobs' : '/api/catalog/import';
  const params = setPageParams(new URLSearchParams({ limit: String(limit) }), page);
  return `${base}?${params.toString()}`;
}

/** Paginated recent async jobs for export studio / catalog import. */
export function RecentAsyncJobsPanel({
  kind,
  limit = DEFAULT_LIMIT,
  title,
  className,
  testId,
}: RecentAsyncJobsPanelProps) {
  const pageLimit = Math.max(1, Math.min(limit, 50));
  const trail = useCursorTrail(`${kind}:${pageLimit}`, pageLimit);
  const { cursor, offset, first } = trail;
  const [jobs, setJobs] = useState<RecentAsyncJobRow[]>([]);
  const [pageInfo, setPageInfo] = useState<PageInfo>(EMPTY_PAGE_INFO);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = testId ?? (kind === 'export' ? 'export-recent-jobs' : 'import-recent-jobs');
  const heading = title ?? (kind === 'export' ? 'Recent export jobs' : 'Recent import jobs');

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(
          recentAsyncJobsUrl(kind, pageLimit, { cursor, offset, includeTotal: first }),
          { cache: 'no-store', signal },
        );
        const body = (await res.json().catch(() => null)) as ListPayload | null;
        if (signal?.aborted) return;
        if (!res.ok || !body || body.success === false) {
          setError(body?.error || `Failed to load jobs (${res.status})`);
          setJobs([]);
          setPageInfo(EMPTY_PAGE_INFO);
          return;
        }
        const page = readPage(body);
        setJobs(Array.isArray(body.jobs) ? body.jobs : []);
        setPageInfo(page);
        // Only the first page is counted; the later ones keep its answer.
        if (first) setTotal(page.total);
      } catch (err) {
        if (signal?.aborted) return;
        setError(err instanceof Error ? err.message : 'Failed to load jobs');
        setJobs([]);
        setPageInfo(EMPTY_PAGE_INFO);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [kind, pageLimit, cursor, offset, first],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const hasNext = hasMoreAfter(pageInfo, offset + jobs.length);

  const columns: DataTableColumn<RecentAsyncJobRow>[] = [
    {
      id: 'job',
      header: 'Job',
      cell: (job) => <span className="font-mono text-xs">{job.job_id}</span>,
    },
    {
      id: 'state',
      header: 'State',
      // `status` resolves through the shared vocabulary, so a running import here is the
      // same amber as a running import in the wizard's own progress badge.
      cell: (job) => <Badge status={job.state}>{job.state}</Badge>,
    },
    ...(kind === 'export'
      ? ([
          { id: 'target', header: 'Target', cell: (job) => job.target ?? '—' },
          {
            id: 'artifact',
            header: 'Artifact',
            cell: (job) => <span className="font-mono text-xs">{job.artifact ?? '—'}</span>,
          },
        ] as DataTableColumn<RecentAsyncJobRow>[])
      : ([
          {
            id: 'progress',
            header: 'Progress',
            cell: (job) => (typeof job.percent === 'number' ? `${job.percent}%` : '—'),
          },
        ] as DataTableColumn<RecentAsyncJobRow>[])),
  ];

  return (
    <section className={className} data-testid={id} aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`} className="mb-2 text-sm font-semibold text-fg">
        {heading}
      </h2>
      <DataTable
        dense
        caption={heading}
        columns={columns}
        rows={jobs}
        getRowId={(job) => job.job_id}
        getRowLabel={(job) => job.job_id}
        loading={loading && jobs.length === 0}
        loadingLabel={`Loading ${kind} jobs…`}
        error={error ? <span data-testid={`${id}-error`}>{error}</span> : undefined}
        onRetry={() => void load()}
        empty={<EmptyState variant="compact" tone="neutral" title="No jobs yet." />}
        footer={
          <DataTableFoot>
            <span data-testid={`${id}-pagination-summary`}>
              {cursorRangeLabel(offset, jobs.length, total, 'job')}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                data-testid={`${id}-prev-page`}
                disabled={first || loading}
                onClick={trail.previous}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                data-testid={`${id}-next-page`}
                disabled={!hasNext || loading}
                onClick={() => trail.next(pageInfo.nextCursor)}
              >
                Next
              </Button>
            </div>
          </DataTableFoot>
        }
      />
    </section>
  );
}

export default RecentAsyncJobsPanel;
