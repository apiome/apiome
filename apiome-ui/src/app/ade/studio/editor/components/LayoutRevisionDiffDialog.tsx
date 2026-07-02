'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {
  X,
  GitCompareArrows,
  ArrowLeftRight,
  Plus,
  Minus,
  Pencil,
  Move,
  Maximize2,
  Link2,
  Settings2,
  Map,
  Loader2,
} from 'lucide-react';
import {
  compareLayouts,
  type LayoutDiffSummary,
  type LayoutDiffEntry,
  type LayoutState,
} from '../../../../../../lib/layout-diff';

export interface RevisionOption {
  id: string;
  revision: number;
  created_at: string;
}

export interface LayoutRevisionDiffDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  revisions: RevisionOption[];
  currentLayout: LayoutState | null;
  onFetchRevisionData: (revisionId: string) => Promise<LayoutState | null>;
}

type DiffSide = { id: string; label: string; state: LayoutState } | null;

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  node: <Move className="h-3.5 w-3.5 shrink-0" aria-hidden />,
  edge: <Link2 className="h-3.5 w-3.5 shrink-0" aria-hidden />,
  viewport: <Maximize2 className="h-3.5 w-3.5 shrink-0" aria-hidden />,
  grid: <Settings2 className="h-3.5 w-3.5 shrink-0" aria-hidden />,
  minimap: <Map className="h-3.5 w-3.5 shrink-0" aria-hidden />,
};

const TYPE_CONFIG = {
  added: {
    icon: <Plus className="h-3 w-3" aria-hidden />,
    badgeClass: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
    textClass: 'text-emerald-700 dark:text-emerald-300',
  },
  removed: {
    icon: <Minus className="h-3 w-3" aria-hidden />,
    badgeClass: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
    textClass: 'text-red-700 dark:text-red-300',
  },
  modified: {
    icon: <Pencil className="h-3 w-3" aria-hidden />,
    badgeClass: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
    textClass: 'text-amber-700 dark:text-amber-300',
  },
  unchanged: {
    icon: null,
    badgeClass: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
    textClass: 'text-gray-500 dark:text-gray-400',
  },
} as const;

function formatRevisionLabel(rev: RevisionOption): string {
  const date = new Date(rev.created_at);
  return `Rev ${rev.revision} · ${date.toLocaleString()}`;
}

function DiffStatBadge({ count, type }: { count: number; type: 'added' | 'removed' | 'modified' }) {
  if (count === 0) return null;
  const config = TYPE_CONFIG[type];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${config.badgeClass}`}
    >
      {config.icon}
      {count} {type}
    </span>
  );
}

function DiffEntryRow({ entry }: { entry: LayoutDiffEntry }) {
  const config = TYPE_CONFIG[entry.type];
  const icon = CATEGORY_ICONS[entry.category];

  return (
    <div className="flex items-start gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-gray-50 dark:hover:bg-gray-800/50">
      <span className={`mt-0.5 shrink-0 ${config.textClass}`}>{config.icon}</span>
      <span className="mt-0.5 shrink-0 text-gray-400 dark:text-gray-500">{icon}</span>
      <div className="min-w-0 flex-1">
        <span className={`font-medium ${config.textClass}`}>{entry.label}</span>
        {entry.changes && entry.changes.length > 0 && (
          <span className="ml-1.5 text-gray-500 dark:text-gray-400">
            ({entry.changes.join(', ')})
          </span>
        )}
      </div>
    </div>
  );
}

function DiffCategorySection({
  title,
  entries,
  unchangedCount,
}: {
  title: string;
  entries: LayoutDiffEntry[];
  unchangedCount?: number;
}) {
  if (entries.length === 0 && (unchangedCount ?? 0) === 0) return null;

  return (
    <div>
      <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
        {title}
      </h4>
      {entries.length === 0 ? (
        <p className="px-2 py-1 text-xs text-gray-400 dark:text-gray-500">No changes</p>
      ) : (
        <div className="space-y-0.5">
          {entries.map((entry) => (
            <DiffEntryRow key={`${entry.category}-${entry.id}-${entry.type}`} entry={entry} />
          ))}
        </div>
      )}
      {(unchangedCount ?? 0) > 0 && (
        <p className="mt-1 px-2 text-[10px] text-gray-400 dark:text-gray-500">
          {unchangedCount} unchanged
        </p>
      )}
    </div>
  );
}

export function LayoutRevisionDiffDialog({
  open,
  onOpenChange,
  revisions,
  currentLayout,
  onFetchRevisionData,
}: LayoutRevisionDiffDialogProps) {
  const [leftId, setLeftId] = useState<string>('');
  const [rightId, setRightId] = useState<string>('current');
  const [leftData, setLeftData] = useState<DiffSide>(null);
  const [rightData, setRightData] = useState<DiffSide>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (revisions.length >= 1) {
      const oldestRevision = revisions[revisions.length - 1];
      setLeftId(oldestRevision.id);
      setRightId('current');
    }
  }, [open, revisions]);

  const fetchSide = useCallback(
    async (sideId: string): Promise<DiffSide> => {
      if (sideId === 'current') {
        return currentLayout
          ? { id: 'current', label: 'Current layout', state: currentLayout }
          : null;
      }
      const rev = revisions.find((r) => r.id === sideId);
      if (!rev) return null;
      const data = await onFetchRevisionData(sideId);
      if (!data) return null;
      return { id: sideId, label: formatRevisionLabel(rev), state: data };
    },
    [currentLayout, onFetchRevisionData, revisions]
  );

  useEffect(() => {
    if (!open || (!leftId && !rightId)) return;
    let cancelled = false;

    (async () => {
      setLoading(true);
      try {
        const [l, r] = await Promise.all([
          leftId ? fetchSide(leftId) : Promise.resolve(null),
          rightId ? fetchSide(rightId) : Promise.resolve(null),
        ]);
        if (!cancelled) {
          setLeftData(l);
          setRightData(r);
        }
      } catch (err) {
        console.error('Error fetching revision data for diff:', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, leftId, rightId, fetchSide]);

  const diff = useMemo<LayoutDiffSummary | null>(() => {
    if (!leftData || !rightData) return null;
    return compareLayouts(leftData.state, rightData.state);
  }, [leftData, rightData]);

  const swapSides = () => {
    setLeftId(rightId);
    setRightId(leftId);
  };

  const selectOptions = useMemo(() => {
    const opts: { value: string; label: string }[] = [
      { value: 'current', label: 'Current layout' },
      ...revisions.map((r) => ({
        value: r.id,
        label: formatRevisionLabel(r),
      })),
    ];
    return opts;
  }, [revisions]);

  const canCompare = revisions.length >= 1;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[1300] bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[1301] w-[min(96vw,52rem)] max-h-[min(92vh,44rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-gray-200 bg-white shadow-xl dark:border-gray-700 dark:bg-gray-900 flex flex-col min-h-0 outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95">
          {/* Header */}
          <div className="flex shrink-0 items-start justify-between gap-3 border-b border-gray-200 px-4 py-3 dark:border-gray-700">
            <div className="flex items-start gap-2 min-w-0">
              <GitCompareArrows
                className="mt-0.5 h-5 w-5 shrink-0 text-indigo-600 dark:text-indigo-400"
                aria-hidden
              />
              <div className="min-w-0">
                <Dialog.Title className="text-sm font-semibold text-gray-900 dark:text-white">
                  Compare layout revisions
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-xs text-gray-500 dark:text-gray-400 leading-snug">
                  Select two revisions (or the current layout) to see what changed — nodes
                  added/removed/moved, edges, viewport, and settings.
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close
              type="button"
              className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>

          {/* Body */}
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3">
            {!canCompare ? (
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Save at least one layout revision to compare. Each named save stores the previous
                state (up to 50).
              </p>
            ) : (
              <div className="space-y-4">
                {/* Selectors */}
                <div className="flex flex-wrap items-end gap-3">
                  <SideSelector
                    label="Left (older)"
                    htmlId="diff-select-left"
                    value={leftId}
                    onChange={setLeftId}
                    options={selectOptions}
                  />
                  <button
                    type="button"
                    onClick={swapSides}
                    className="mb-0.5 inline-flex items-center gap-1.5 self-end rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                  >
                    <ArrowLeftRight className="h-3.5 w-3.5" aria-hidden />
                    Swap
                  </button>
                  <SideSelector
                    label="Right (newer)"
                    htmlId="diff-select-right"
                    value={rightId}
                    onChange={setRightId}
                    options={selectOptions}
                  />
                </div>

                {/* Loading */}
                {loading && (
                  <div className="flex items-center gap-2 py-4 text-sm text-gray-500 dark:text-gray-400">
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                    Loading revision data…
                  </div>
                )}

                {/* Diff results */}
                {!loading && diff && (
                  <div className="space-y-4">
                    {/* Summary bar */}
                    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-800/60">
                      {diff.totalChanges === 0 ? (
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                          No differences found
                        </span>
                      ) : (
                        <>
                          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                            {diff.totalChanges} change{diff.totalChanges !== 1 ? 's' : ''}
                          </span>
                          <DiffStatBadge
                            count={diff.nodes.added.length + diff.edges.added.length}
                            type="added"
                          />
                          <DiffStatBadge
                            count={diff.nodes.removed.length + diff.edges.removed.length}
                            type="removed"
                          />
                          <DiffStatBadge
                            count={
                              diff.nodes.modified.length +
                              diff.edges.modified.length +
                              (diff.viewport ? 1 : 0) +
                              (diff.gridSettings ? 1 : 0) +
                              (diff.minimapSettings ? 1 : 0)
                            }
                            type="modified"
                          />
                        </>
                      )}
                    </div>

                    {/* Detail sections */}
                    {diff.totalChanges > 0 && (
                      <div className="space-y-3 divide-y divide-gray-100 dark:divide-gray-800">
                        <DiffCategorySection
                          title="Nodes"
                          entries={[
                            ...diff.nodes.added,
                            ...diff.nodes.removed,
                            ...diff.nodes.modified,
                          ]}
                          unchangedCount={diff.nodes.unchanged}
                        />
                        <DiffCategorySection
                          title="Edges"
                          entries={[
                            ...diff.edges.added,
                            ...diff.edges.removed,
                            ...diff.edges.modified,
                          ]}
                          unchangedCount={diff.edges.unchanged}
                        />
                        {(diff.viewport || diff.gridSettings || diff.minimapSettings) && (
                          <DiffCategorySection
                            title="Settings"
                            entries={[
                              ...(diff.viewport ? [diff.viewport] : []),
                              ...(diff.gridSettings ? [diff.gridSettings] : []),
                              ...(diff.minimapSettings ? [diff.minimapSettings] : []),
                            ]}
                          />
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* No data state */}
                {!loading && !diff && leftId && rightId && (
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Could not load one or both revisions for comparison.
                  </p>
                )}
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function SideSelector({
  label,
  htmlId,
  value,
  onChange,
  options,
}: {
  label: string;
  htmlId: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <label
        htmlFor={htmlId}
        className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
      >
        {label}
      </label>
      <select
        id={htmlId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-gray-200 bg-white px-2 py-2 text-xs text-gray-800 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
