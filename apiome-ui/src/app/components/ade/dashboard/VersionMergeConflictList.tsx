'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '../../ui/Dialog';
import {
  filterMergeConflictRows,
  formatMergeConflictKinds,
  mergeConflictKindSignature,
  type MergeConflictResolutionChoice,
} from '../../../../../lib/version-merge';
import { cn } from '../../../../../lib/utils';

export interface VersionMergeConflictListProps {
  conflicts: Array<{ path: string; kinds: string[] }>;
  targetBranchName: string;
  sourceBranchName: string;
  resolutions: Record<string, MergeConflictResolutionChoice | null>;
  onResolve: (path: string, choice: MergeConflictResolutionChoice) => void;
  onBulkResolve: (paths: string[], choice: MergeConflictResolutionChoice) => void;
  className?: string;
}

function resolutionLabel(choice: MergeConflictResolutionChoice | null | undefined): string {
  if (choice === 'mine') return 'Target (mine)';
  if (choice === 'theirs') return 'Source (theirs)';
  if (choice === 'manual') return 'Manual';
  return 'Unresolved';
}

export function VersionMergeConflictList({
  conflicts,
  targetBranchName,
  sourceBranchName,
  resolutions,
  onResolve,
  onBulkResolve,
  className = '',
}: VersionMergeConflictListProps) {
  const [manualPath, setManualPath] = useState<string | null>(null);
  const [pathFilter, setPathFilter] = useState('');
  const [kindFilter, setKindFilter] = useState<string | 'all'>('all');

  const kindOptions = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of conflicts) {
      const sig = mergeConflictKindSignature(row.kinds);
      if (!map.has(sig)) {
        map.set(sig, formatMergeConflictKinds(row.kinds));
      }
    }
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [conflicts]);

  useEffect(() => {
    if (kindFilter === 'all') return;
    const valid = kindOptions.some(([sig]) => sig === kindFilter);
    if (!valid) setKindFilter('all');
  }, [kindFilter, kindOptions]);

  const filteredConflicts = useMemo(
    () => filterMergeConflictRows(conflicts, { pathContains: pathFilter, kindSignature: kindFilter }),
    [conflicts, pathFilter, kindFilter]
  );

  const applyBulk = (paths: string[], choice: MergeConflictResolutionChoice) => {
    if (paths.length === 0) return;
    onBulkResolve(paths, choice);
  };

  if (conflicts.length === 0) return null;

  const allPaths = conflicts.map((c) => c.path);
  const shownPaths = filteredConflicts.map((c) => c.path);

  return (
    <>
      <div
        className={cn(
          'rounded-xl border border-amber-200 dark:border-amber-800 bg-white dark:bg-gray-800 overflow-hidden',
          className
        )}
      >
        <div className="flex items-start gap-3 p-4 border-b border-amber-200 dark:border-amber-800 bg-amber-50/80 dark:bg-amber-900/20">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300">
            <AlertTriangle className="h-5 w-5" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">Merge conflicts</h3>
            <p className="mt-0.5 text-sm text-amber-900/90 dark:text-amber-200/90">
              {conflicts.length} path{conflicts.length !== 1 ? 's' : ''} need a resolution before apply can succeed on the
              server. Choices are stored in this session for the upcoming merge-resolution API.
            </p>
            <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">
              <span className="font-medium text-gray-800 dark:text-gray-200">Mine</span> = target branch{' '}
              <span className="font-mono">{targetBranchName || '—'}</span>
              {' · '}
              <span className="font-medium text-gray-800 dark:text-gray-200">Theirs</span> = source branch{' '}
              <span className="font-mono">{sourceBranchName || '—'}</span>
            </p>
          </div>
        </div>

        <div className="px-4 py-3 border-b border-amber-200 dark:border-amber-800 bg-amber-50/40 dark:bg-amber-950/20 space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end">
            <div className="min-w-0 flex-1 space-y-1">
              <label htmlFor="merge-conflict-path-filter" className="text-xs font-medium text-gray-700 dark:text-gray-300">
                Filter paths
              </label>
              <Input
                id="merge-conflict-path-filter"
                type="search"
                placeholder="Substring match on path…"
                value={pathFilter}
                onChange={(e) => setPathFilter(e.target.value)}
                className="h-9 text-xs"
                autoComplete="off"
              />
            </div>
            <div className="w-full sm:w-56 space-y-1">
              <label htmlFor="merge-conflict-kind-filter" className="text-xs font-medium text-gray-700 dark:text-gray-300">
                Conflict type
              </label>
              <select
                id="merge-conflict-kind-filter"
                value={kindFilter}
                onChange={(e) => setKindFilter(e.target.value === 'all' ? 'all' : e.target.value)}
                className={cn(
                  'flex h-9 w-full rounded-md border border-slate-300 dark:border-slate-600',
                  'bg-white dark:bg-slate-800 px-2 py-1.5 text-xs',
                  'text-slate-900 dark:text-slate-100',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/70 focus-visible:ring-offset-2',
                  'ring-offset-white dark:ring-offset-slate-900'
                )}
              >
                <option value="all">All types</option>
                {kindOptions.map(([sig, label]) => (
                  <option key={sig} value={sig}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <p className="text-xs text-gray-600 dark:text-gray-400">
            Filter matches <span className="font-medium text-gray-800 dark:text-gray-200">{filteredConflicts.length}</span> of{' '}
            <span className="font-medium text-gray-800 dark:text-gray-200">{conflicts.length}</span> path
            {conflicts.length !== 1 ? 's' : ''}. Bulk actions for <span className="font-medium">shown</span> use this
            filter.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
            <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 shrink-0">Bulk (shown)</span>
            <div className="flex flex-wrap gap-1.5">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="text-xs"
                disabled={shownPaths.length === 0}
                onClick={() => applyBulk(shownPaths, 'mine')}
                title={`Set Target (mine) for ${shownPaths.length} path(s) matching the filter`}
                aria-label={`Bulk mine for ${shownPaths.length} path(s) matching filter`}
              >
                Mine
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="text-xs"
                disabled={shownPaths.length === 0}
                onClick={() => applyBulk(shownPaths, 'theirs')}
                title={`Set Source (theirs) for ${shownPaths.length} path(s) matching the filter`}
                aria-label={`Bulk theirs for ${shownPaths.length} path(s) matching filter`}
              >
                Theirs
              </Button>
            </div>
            <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 shrink-0 sm:ml-2">Bulk (all)</span>
            <div className="flex flex-wrap gap-1.5">
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="text-xs"
                onClick={() => applyBulk(allPaths, 'mine')}
                title={`Set Target (mine) for all ${allPaths.length} conflict path(s)`}
                aria-label={`Bulk mine for all ${allPaths.length} conflict path(s)`}
              >
                Mine
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="text-xs"
                onClick={() => applyBulk(allPaths, 'theirs')}
                title={`Set Source (theirs) for all ${allPaths.length} conflict path(s)`}
                aria-label={`Bulk theirs for all ${allPaths.length} conflict path(s)`}
              >
                Theirs
              </Button>
            </div>
          </div>
        </div>

        <div className="overflow-x-auto max-h-72 overflow-y-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                <th scope="col" className="text-left py-2.5 px-3 font-semibold text-gray-700 dark:text-gray-300">Path</th>
                <th scope="col" className="text-left py-2.5 px-3 font-semibold text-gray-700 dark:text-gray-300 whitespace-nowrap">
                  Type
                </th>
                <th scope="col" className="text-left py-2.5 px-3 font-semibold text-gray-700 dark:text-gray-300 whitespace-nowrap">
                  Resolution
                </th>
                <th scope="col" className="text-left py-2.5 px-3 font-semibold text-gray-700 dark:text-gray-300 min-w-[220px]">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {conflicts.map((row) => {
                const choice = resolutions[row.path] ?? null;
                const unresolved = choice === null || choice === undefined;
                return (
                  <tr
                    key={row.path}
                    className={cn(
                      'border-b border-gray-100 dark:border-gray-800 last:border-0',
                      unresolved && 'bg-amber-50/90 dark:bg-amber-950/30'
                    )}
                  >
                    <td className="py-2.5 px-3 font-mono text-xs text-gray-900 dark:text-gray-100 break-all align-top">
                      {row.path}
                    </td>
                    <td className="py-2.5 px-3 text-gray-700 dark:text-gray-300 align-top whitespace-nowrap">
                      {formatMergeConflictKinds(row.kinds)}
                    </td>
                    <td className="py-2.5 px-3 align-top">
                      <span
                        className={cn(
                          'inline-flex rounded-md px-2 py-0.5 text-xs font-medium',
                          unresolved
                            ? 'bg-amber-200 text-amber-950 dark:bg-amber-900/50 dark:text-amber-100'
                            : 'bg-slate-200 text-slate-900 dark:bg-slate-700 dark:text-slate-100'
                        )}
                      >
                        {resolutionLabel(choice)}
                      </span>
                    </td>
                    <td className="py-2 px-3 align-top">
                      <div className="flex flex-wrap gap-1.5">
                        <Button
                          type="button"
                          size="sm"
                          variant={choice === 'mine' ? 'default' : 'outline'}
                          className="text-xs"
                          onClick={() => onResolve(row.path, 'mine')}
                          title={`Keep target (${targetBranchName}) at this path`}
                        >
                          Mine
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant={choice === 'theirs' ? 'default' : 'outline'}
                          className="text-xs"
                          onClick={() => onResolve(row.path, 'theirs')}
                          title={`Take source (${sourceBranchName}) at this path`}
                        >
                          Theirs
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant={choice === 'manual' ? 'secondary' : 'outline'}
                          className="text-xs"
                          onClick={() => {
                            onResolve(row.path, 'manual');
                            setManualPath(row.path);
                          }}
                        >
                          Manual
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={manualPath !== null} onOpenChange={(o) => !o && setManualPath(null)}>
        <DialogContent className="max-w-lg" aria-describedby="merge-manual-desc">
          <DialogHeader>
            <DialogTitle>Manual resolution</DialogTitle>
            <DialogDescription id="merge-manual-desc">
              Path <span className="font-mono text-gray-900 dark:text-gray-100">{manualPath}</span> is marked for manual
              merge. A future release will open a side-by-side diff and let you submit the merged fragment to the merge
              session API.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" onClick={() => setManualPath(null)}>
              OK
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
