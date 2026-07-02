'use client';

import React, { useEffect, useLayoutEffect, useMemo, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X, Columns2, ArrowLeftRight, Image as ImageIcon } from 'lucide-react';
import {
  formatQuickSnapshotCaption,
  quickSnapshotAuthorDisplay,
  quickSnapshotCountsSummary,
  quickSnapshotOptionLabel,
  type QuickLayoutSnapshot,
} from '../lib/quick-layout-snapshots';

export interface QuickSnapshotCompareDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  snapshots: QuickLayoutSnapshot[];
}

export function QuickSnapshotCompareDialog({
  open,
  onOpenChange,
  snapshots,
}: QuickSnapshotCompareDialogProps) {
  const [leftId, setLeftId] = useState<string | null>(null);
  const [rightId, setRightId] = useState<string | null>(null);

  useLayoutEffect(() => {
    if (!open || snapshots.length < 2) return;
    const ids = new Set(snapshots.map((s) => s.id));
    setLeftId((L) => (L && ids.has(L) ? L : snapshots[1].id));
    setRightId((R) => (R && ids.has(R) ? R : snapshots[0].id));
  }, [open, snapshots]);

  const byId = useMemo(() => new Map(snapshots.map((s) => [s.id, s])), [snapshots]);
  const left = leftId ? byId.get(leftId) : undefined;
  const right = rightId ? byId.get(rightId) : undefined;

  useEffect(() => {
    if (!open || !leftId || !rightId || leftId !== rightId || snapshots.length < 2) return;
    const alt = snapshots.find((s) => s.id !== leftId);
    if (alt) setRightId(alt.id);
  }, [open, leftId, rightId, snapshots]);

  const swapSides = () => {
    setLeftId(rightId);
    setRightId(leftId);
  };

  const canCompare = snapshots.length >= 2;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[1300] bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-[1301] w-[min(96vw,56rem)] max-h-[min(92vh,44rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-gray-200 bg-white shadow-xl dark:border-gray-700 dark:bg-gray-900 flex flex-col min-h-0 outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
        >
          <div className="flex shrink-0 items-start justify-between gap-3 border-b border-gray-200 px-4 py-3 dark:border-gray-700">
            <div className="flex items-start gap-2 min-w-0">
              <Columns2 className="mt-0.5 h-5 w-5 shrink-0 text-indigo-600 dark:text-indigo-400" aria-hidden />
              <div className="min-w-0">
                <Dialog.Title className="text-sm font-semibold text-gray-900 dark:text-white">
                  Compare quick snapshots
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-xs text-gray-500 dark:text-gray-400 leading-snug">
                  Side-by-side preview and layout counts. List order is newest first; defaults put the older capture on
                  the left and the newer on the right.
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

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3">
            {!canCompare ? (
              <p className="text-sm text-gray-600 dark:text-gray-400">Capture at least two quick snapshots to compare.</p>
            ) : (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={swapSides}
                    disabled={!left || !right}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                  >
                    <ArrowLeftRight className="h-3.5 w-3.5" aria-hidden />
                    Swap sides
                  </button>
                </div>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {(
                    [
                      { label: 'Left', id: leftId, setId: setLeftId, snap: left },
                      { label: 'Right', id: rightId, setId: setRightId, snap: right },
                    ] as const
                  ).map(({ label, id, setId, snap }) => {
                    const snapAuthor = snap ? quickSnapshotAuthorDisplay(snap) : undefined;
                    return (
                    <div key={label} className="flex min-w-0 flex-col gap-2">
                      <label
                        htmlFor={`snapshot-select-${label.toLowerCase()}`}
                        className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
                      >
                        {label}
                      </label>
                      <select
                        id={`snapshot-select-${label.toLowerCase()}`}
                        value={id ?? ''}
                        onChange={(e) => setId(e.target.value || null)}
                        className="w-full rounded-lg border border-gray-200 bg-white px-2 py-2 text-xs text-gray-800 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
                      >
                        {snapshots.map((s) => (
                          <option key={s.id} value={s.id}>
                            {quickSnapshotOptionLabel(s)}
                          </option>
                        ))}
                      </select>
                      <div className="overflow-hidden rounded-lg border border-gray-200 bg-gray-50 dark:border-gray-600 dark:bg-gray-800/60">
                        <div className="relative aspect-[5/3] w-full bg-gray-100 dark:bg-gray-900">
                          {snap?.thumbnailDataUrl ? (
                            <img
                              src={snap.thumbnailDataUrl}
                              alt=""
                              className="absolute inset-0 h-full w-full object-cover"
                            />
                          ) : (
                            <div
                              className="absolute inset-0 flex flex-col items-center justify-center gap-1 px-2 text-center text-gray-400 dark:text-gray-500"
                              role="img"
                              aria-label="No preview"
                            >
                              <ImageIcon className="h-6 w-6 opacity-60" aria-hidden />
                              <span className="text-[10px]">No preview</span>
                            </div>
                          )}
                        </div>
                        <div className="border-t border-gray-200 px-2 py-1.5 text-[10px] leading-snug text-gray-600 dark:text-gray-300 dark:border-gray-700">
                          {snap ? (
                            <>
                              <p className="font-medium tabular-nums">{formatQuickSnapshotCaption(snap.createdAt)}</p>
                              {snapAuthor ? <p className="text-gray-600 dark:text-gray-300">{snapAuthor}</p> : null}
                              {snap.summary?.trim() ? (
                                <p className="font-medium text-gray-800 dark:text-gray-100">{snap.summary.trim()}</p>
                              ) : null}
                              <p className="text-gray-500 dark:text-gray-400">{quickSnapshotCountsSummary(snap)}</p>
                              {snap.description?.trim() ? (
                                <p className="line-clamp-3 text-gray-500 dark:text-gray-400">{snap.description.trim()}</p>
                              ) : null}
                            </>
                          ) : (
                            <p className="text-gray-500">Select a snapshot</p>
                          )}
                        </div>
                      </div>
                    </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
