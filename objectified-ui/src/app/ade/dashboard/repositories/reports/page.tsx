'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { ChevronLeft, Download, FileBarChart2, Search, Timer } from 'lucide-react';
import { Button, buttonVariants } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Alert } from '@/app/components/ui/Alert';
import { Skeleton } from '@/app/components/ui/Skeleton';
import { cn } from '@lib/utils';
import {
  dashboardContentStackClass,
  dashboardMainClass,
  repositoryHeaderEyebrowClass,
  repositoryHeaderIconTileClass,
  repositoryHeaderShellClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';

const PROVIDERS = [
  { id: 'all', label: 'All' },
  { id: 'github', label: 'GitHub' },
  { id: 'gitlab', label: 'GitLab' },
  { id: 'bitbucket', label: 'Bitbucket' },
] as const;

const STATUS_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'importable', label: 'Importable' },
  { id: 'imported', label: 'Imported' },
  { id: 'failing', label: 'Failing' },
  { id: 'awaiting', label: 'Awaiting selection' },
  { id: 'stale', label: 'Stale' },
] as const;

type ScanReportTotals = {
  discovered: number;
  importable: number;
  imported: number;
  failing: number;
  parseError: number;
  manifestError: number;
  awaitingSelection: number;
  scanFailed: boolean;
};

type ScanReportRow = {
  repositoryId: string;
  fullName: string;
  provider: string;
  branchCount: number;
  lastScanAt: string | null;
  lastScanId: string | null;
  totals: ScanReportTotals | null;
  attentionScore: number;
  stale: boolean;
};

function formatLastScan(value: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString();
}

function providerBarClass(provider: string): string {
  if (provider === 'gitlab') return 'bg-orange-500';
  if (provider === 'bitbucket') return 'bg-sky-500';
  return 'bg-gray-700 dark:bg-gray-300';
}

function attentionCell(
  item: Pick<ScanReportRow, 'stale' | 'totals' | 'attentionScore'>,
): { label: string; title: string } {
  if (item.stale) {
    return { label: 'stale', title: 'Last scan is older than 7 days' };
  }
  if (item.totals?.scanFailed) {
    return { label: '—', title: 'Last scan did not complete successfully' };
  }
  const f = item.totals?.failing ?? 0;
  const a = item.totals?.awaitingSelection ?? 0;
  if (f + a < 1) {
    return { label: '—', title: 'No failing files or specs awaiting selection' };
  }
  return {
    label: `⚠ ${f + a}`,
    title: `${f} failing file(s), ${a} awaiting selection`,
  };
}

export default function ScanReportsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const listMsgId = useId();

  const [rows, setRows] = useState<ScanReportRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  const urlProvider = searchParams.get('provider') || 'all';
  const urlStatus = searchParams.get('status') || 'all';
  const urlQ = searchParams.get('q') || '';
  const urlPage = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const [qDraft, setQDraft] = useState(urlQ);
  const qDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setQDraft(urlQ);
  }, [urlQ]);

  const setQuery = useCallback(
    (next: Record<string, string | number | null | undefined>) => {
      const p = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(next)) {
        if (v == null || v === '') p.delete(k);
        else p.set(k, String(v));
      }
      router.push(`${pathname}?${p.toString()}`);
    },
    [router, pathname, searchParams],
  );

  const load = useCallback(async () => {
    setIsLoading(true);
    setError('');
    try {
      const p = new URLSearchParams();
      p.set('provider', urlProvider);
      p.set('status', urlStatus);
      if (urlQ.trim()) p.set('q', urlQ.trim());
      p.set('page', String(urlPage));
      p.set('pageSize', String(pageSize));
      const res = await fetch(`/api/repositories/scan-reports?${p.toString()}`);
      const body = await res.json();
      if (!res.ok || !body.success) {
        throw new Error(typeof body.error === 'string' ? body.error : 'Failed to load scan reports');
      }
      const d = body.data;
      setRows(d.items ?? []);
      setTotal(d.total ?? 0);
      setPage(d.page ?? 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load');
      setRows([]);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  }, [pageSize, urlPage, urlProvider, urlQ, urlStatus]);

  useEffect(() => {
    void load();
  }, [load]);

  const liveMessage = useMemo(() => {
    if (isLoading) return 'Loading scan reports';
    if (error) return error;
    return `Scan reports: ${rows.length} on this page, ${total} match filters.`;
  }, [error, isLoading, rows.length, total]);

  return (
    <>
      <header className={repositoryHeaderShellClass}>
        <div className="px-6 py-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <span className={repositoryHeaderIconTileClass} aria-hidden>
                <FileBarChart2 className="w-5 h-5" />
              </span>
              <div>
                <p className={repositoryHeaderEyebrowClass}>
                  <Link
                    className="inline-flex items-center gap-1 text-indigo-600 dark:text-indigo-400 hover:underline"
                    href="/ade/dashboard/repositories"
                  >
                    <ChevronLeft className="w-4 h-4" />
                    Repositories
                  </Link>
                  <span className="mx-2 text-gray-400" aria-hidden>
                    /
                  </span>
                  Scan reports
                </p>
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Scanned repository report</h1>
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
                  Tenant-wide view of the latest scan materialization per repository (totals are pre-aggregated on the
                  server).
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled
                className="gap-1.5"
                title="Planned in REPO-10.4"
                aria-label="Export report; coming soon"
              >
                <Download className="w-4 h-4" />
                Export
              </Button>
            </div>
          </div>
        </div>
      </header>

      <div id={listMsgId} role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {liveMessage}
      </div>

      <main className={dashboardMainClass}>
        <div className={dashboardContentStackClass}>
          {error && (
            <Alert variant="error" onClose={() => setError('')}>
              {error}
            </Alert>
          )}

          <section
            className="rounded-lg border border-gray-200/80 dark:border-slate-600/50 bg-white/90 dark:bg-slate-800/30 p-4"
            aria-label="Scan report filters"
          >
            <div className="flex flex-col gap-4">
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
                  Provider
                </p>
                <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by provider">
                  {PROVIDERS.map((p) => {
                    const active = p.id === urlProvider;
                    return (
                      <button
                        type="button"
                        key={p.id}
                        onClick={() => setQuery({ provider: p.id, page: 1 })}
                        className={cn(
                          'px-3 py-1.5 text-sm rounded-md border transition-colors',
                          active
                            ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/40 text-indigo-800 dark:text-indigo-200'
                            : 'border-gray-200 dark:border-slate-600 hover:border-gray-300',
                        )}
                      >
                        {p.label}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
                  Status
                </p>
                <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by scan status">
                  {STATUS_FILTERS.map((p) => {
                    const active = p.id === urlStatus;
                    return (
                      <button
                        type="button"
                        key={p.id}
                        onClick={() => setQuery({ status: p.id, page: 1 })}
                        className={cn(
                          'px-3 py-1.5 text-sm rounded-md border transition-colors',
                          active
                            ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/40 text-indigo-800 dark:text-indigo-200'
                            : 'border-gray-200 dark:border-slate-600 hover:border-gray-300',
                        )}
                      >
                        {p.label}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="flex flex-col sm:flex-row sm:items-center gap-3 max-w-2xl">
                <div className="flex-1 relative">
                  <Search
                    className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
                    aria-hidden
                  />
                  <Input
                    className="pl-8"
                    placeholder="Search by repository name, slug, or id…"
                    value={qDraft}
                    onChange={(e) => {
                      const v = e.target.value;
                      setQDraft(v);
                      if (qDebounce.current) clearTimeout(qDebounce.current);
                      qDebounce.current = setTimeout(() => {
                        setQuery({ q: v || null, page: 1 });
                      }, 400);
                    }}
                    aria-label="Search repositories"
                  />
                </div>
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-gray-200/80 dark:border-slate-600/50 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm" aria-describedby={listMsgId}>
                <caption className="text-left text-xs text-gray-500 dark:text-gray-400 px-3 py-2">
                  Spec columns: I=importable · A=imported (committed) · F=failing · S=awaiting selection. Sorted by
                  attention (highest first), then last scan.
                </caption>
                <thead className="bg-gray-50/90 dark:bg-slate-800/50">
                  <tr>
                    <th scope="col" className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase text-gray-500">
                      Repository
                    </th>
                    <th scope="col" className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase text-gray-500">
                      Provider
                    </th>
                    <th scope="col" className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase text-gray-500">
                      Branches
                    </th>
                    <th scope="col" className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase text-gray-500">
                      Last scan
                    </th>
                    <th
                      scope="col"
                      className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase text-gray-500"
                      aria-sort="descending"
                    >
                      Specs (I / A / F / S)
                    </th>
                    <th scope="col" className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase text-gray-500">
                      Attention
                    </th>
                    <th scope="col" className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase text-gray-500">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {isLoading ? (
                    <tr>
                      <td colSpan={7} className="p-4">
                        <div className="space-y-2" aria-label="Loading scan report rows">
                          {Array.from({ length: 6 }).map((_, i) => (
                            <Skeleton key={i} className="h-7 w-full" />
                          ))}
                        </div>
                      </td>
                    </tr>
                  ) : (
                    rows.map((item) => {
                      const t = item.totals;
                      const i0 = t?.importable ?? 0;
                      const a0 = t?.imported ?? 0;
                      const f0 = t?.failing ?? (t?.parseError ?? 0) + (t?.manifestError ?? 0);
                      const s0 = t?.awaitingSelection ?? 0;
                      const att = attentionCell(item);
                      return (
                        <tr key={item.repositoryId} className="border-t border-gray-200/60 dark:border-slate-600/30">
                          <td className="px-3 py-2.5">
                            {item.lastScanId ? (
                              <Link
                                className="font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
                                href={`/ade/dashboard/repositories/${item.repositoryId}/reports/${item.lastScanId}`}
                              >
                                {item.fullName}
                              </Link>
                            ) : (
                              <span className="font-medium text-gray-800 dark:text-gray-100">{item.fullName}</span>
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            <div className="inline-flex items-center gap-1.5">
                              <span className={cn('w-1.5 h-4 rounded-sm', providerBarClass(item.provider))} />
                              <span className="capitalize text-gray-700 dark:text-gray-200">{item.provider}</span>
                            </div>
                          </td>
                          <td className="px-3 py-2.5 tabular-nums text-gray-700 dark:text-gray-200">
                            {item.branchCount}
                          </td>
                          <td className="px-3 py-2.5 text-gray-700 dark:text-gray-200 whitespace-nowrap">
                            {item.stale ? (
                              <span
                                className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-300"
                                title="Last scan older than 7 days"
                              >
                                <Timer className="w-3.5 h-3.5" />
                                {formatLastScan(item.lastScanAt)}
                              </span>
                            ) : (
                              formatLastScan(item.lastScanAt)
                            )}
                          </td>
                          <td className="px-3 py-2.5 font-mono text-xs text-gray-800 dark:text-gray-100 tabular-nums">
                            {i0} / {a0} / {f0} / {s0}
                          </td>
                          <td className="px-3 py-2.5 text-gray-800 dark:text-gray-100" title={att.title}>
                            {att.label}
                          </td>
                          <td className="px-3 py-2.5">
                            <div className="flex gap-2">
                              {item.lastScanId ? (
                                <Link
                                  className={buttonVariants({ size: 'sm', variant: 'ghost' })}
                                  href={`/ade/dashboard/repositories/${item.repositoryId}/reports/${item.lastScanId}`}
                                >
                                  Open report
                                </Link>
                              ) : null}
                              <Link
                                className={buttonVariants({ size: 'sm', variant: 'outline' })}
                                href={`/ade/dashboard/repositories/${item.repositoryId}`}
                              >
                                Repository
                              </Link>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
            {!isLoading && total === 0 && (
              <p className="p-4 text-sm text-gray-500 dark:text-gray-400">No repositories match the current filters.</p>
            )}
            {!isLoading && total > pageSize && (
              <div className="flex items-center justify-between border-t border-gray-200/60 dark:border-slate-600/30 px-3 py-2 text-xs text-gray-500">
                <span>
                  Page {page} · {total} total
                </span>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={urlPage <= 1}
                    onClick={() => setQuery({ page: String(Math.max(1, urlPage - 1)) })}
                  >
                    Previous
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={urlPage * pageSize >= total}
                    onClick={() => setQuery({ page: String(urlPage + 1) })}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </section>
        </div>
      </main>
    </>
  );
}
