'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useStudio } from '../StudioContext';
import { formatRelativeTime } from '@/app/ade/dashboard/versions/version-history-dag';
import { cn } from '@lib/utils';
import { getVersionRevisionNote } from '@/app/utils/version-display';

const POLL_MS = 30_000;

type TickerRow = {
  id: string;
  version_id: string;
  description?: string | null;
  shortMessage?: string | null;
  published?: boolean;
  created_at?: string | null;
  parent_version_id?: string | null;
  creator_name?: string | null;
};

export function BranchRecentTicker() {
  const router = useRouter();
  const { selectedProjectId, selectedBranchId, versionBranchesByProjectId } = useStudio();

  const [rows, setRows] = useState<TickerRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [tabVisible, setTabVisible] = useState(true);

  const branchName = useMemo(() => {
    if (!selectedProjectId || !selectedBranchId) return null;
    const branches = versionBranchesByProjectId[selectedProjectId];
    return branches?.find((b) => b.id === selectedBranchId)?.name ?? null;
  }, [selectedProjectId, selectedBranchId, versionBranchesByProjectId]);

  const branchTipFromContext = useMemo(() => {
    if (!selectedProjectId || !selectedBranchId) return null;
    const branches = versionBranchesByProjectId[selectedProjectId];
    return branches?.find((b) => b.id === selectedBranchId)?.tip_version_id ?? null;
  }, [selectedProjectId, selectedBranchId, versionBranchesByProjectId]);

  const load = useCallback(async () => {
    if (!selectedProjectId?.trim() || !selectedBranchId?.trim()) {
      setRows([]);
      return;
    }
    setLoading(true);
    try {
      const qs = new URLSearchParams({
        projectId: selectedProjectId,
        branchId: selectedBranchId,
        limit: '3',
      });
      const r = await fetch(`/api/versions?${qs.toString()}`);
      const d = (await r.json()) as { success?: boolean; versions?: TickerRow[] };
      if (!r.ok || !d.success || !Array.isArray(d.versions)) {
        setRows([]);
        return;
      }
      setRows(d.versions);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [selectedProjectId, selectedBranchId]);

  useEffect(() => {
    const onVis = () => setTabVisible(document.visibilityState === 'visible');
    onVis();
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  useEffect(() => {
    if (!tabVisible || !selectedProjectId || !selectedBranchId) return;
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [tabVisible, selectedProjectId, selectedBranchId, load]);

  const effectiveTipId = rows[0]?.id ?? branchTipFromContext ?? null;

  const openCompare = useCallback(
    (row: TickerRow) => {
      if (!selectedProjectId || !effectiveTipId) return;
      let compareBase = row.id;
      const compareHead = effectiveTipId;
      if (row.id === effectiveTipId) {
        const parent = row.parent_version_id?.trim();
        if (!parent) return;
        compareBase = parent;
      }
      if (compareBase === compareHead) return;
      const qs = new URLSearchParams({
        projectId: selectedProjectId,
        compareOpen: '1',
        compareBase,
        compareHead,
      });
      router.push(`/ade/dashboard/versions?${qs.toString()}`);
    },
    [selectedProjectId, effectiveTipId, router]
  );

  if (!selectedProjectId || !selectedBranchId) return null;

  const title = branchName ? `Recent on ${branchName}` : 'Recent on branch';

  return (
    <div
      className={cn(
        'max-w-[min(22rem,94vw)] rounded-lg border border-gray-200/55 dark:border-gray-600/45',
        'bg-white/45 dark:bg-gray-900/40 px-2.5 py-1.5 text-left shadow-md backdrop-blur-md',
        'text-gray-800 dark:text-gray-200'
      )}
      aria-label={title}
    >
      <div className="mb-1 flex items-center justify-between gap-2 border-b border-gray-200/60 pb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:border-gray-600/50 dark:text-gray-400">
        <span className="min-w-0 truncate">{title}</span>
        {loading && (
          <span className="shrink-0 text-[10px] font-normal normal-case text-gray-400">Updating…</span>
        )}
      </div>
      {rows.length === 0 && !loading ? (
        <p className="text-[11px] text-gray-500 dark:text-gray-400">No commits on this lineage yet.</p>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {rows.map((row) => {
            const rel = formatRelativeTime(row.created_at ?? null);
            const author = row.creator_name?.trim() || '—';
            const note = getVersionRevisionNote(row);
            const msg = note || row.version_id;
            return (
              <li key={row.id}>
                <button
                  type="button"
                  onClick={() => openCompare(row)}
                  className={cn(
                    'flex w-full min-w-0 flex-col items-start rounded-md px-1 py-0.5 text-left transition-colors',
                    'hover:bg-gray-100/80 dark:hover:bg-gray-800/60',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40'
                  )}
                >
                  <span className="w-full min-w-0 truncate text-[11px] font-medium leading-tight text-gray-900 dark:text-gray-100">
                    {msg}
                  </span>
                  <span className="text-[10px] leading-tight text-gray-500 dark:text-gray-400">
                    {author}
                    {rel ? (
                      <>
                        {' '}
                        · {rel}
                      </>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
