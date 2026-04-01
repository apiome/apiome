'use client';

import React, { useEffect, useMemo, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import * as ToggleGroup from '@radix-ui/react-toggle-group';
import { X, LayoutGrid, Search, Image as ImageIcon } from 'lucide-react';
import {
  formatQuickSnapshotCaption,
  quickSnapshotAuthorDisplay,
  quickSnapshotCountsSummary,
  quickSnapshotMatchesSearch,
  type QuickLayoutSnapshot,
} from '../lib/quick-layout-snapshots';

export type QuickSnapshotPreviewFilter = 'all' | 'with' | 'without';
export type QuickSnapshotSortOrder = 'newest' | 'oldest';

export interface QuickSnapshotGalleryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  snapshots: QuickLayoutSnapshot[];
  onRestore: (snapshot: QuickLayoutSnapshot) => void;
  restoreDisabled: boolean;
  /** Shown as title/tooltip when restore is disabled (e.g. read-only). */
  restoreDisabledReason?: string;
}

export function QuickSnapshotGalleryDialog({
  open,
  onOpenChange,
  snapshots,
  onRestore,
  restoreDisabled,
  restoreDisabledReason,
}: QuickSnapshotGalleryDialogProps) {
  const [query, setQuery] = useState('');
  const [previewFilter, setPreviewFilter] = useState<QuickSnapshotPreviewFilter>('all');
  const [sortOrder, setSortOrder] = useState<QuickSnapshotSortOrder>('newest');

  useEffect(() => {
    if (!open) {
      setQuery('');
      setPreviewFilter('all');
      setSortOrder('newest');
    }
  }, [open]);

  const filteredSorted = useMemo(() => {
    let list = snapshots.filter((s) => quickSnapshotMatchesSearch(s, query));
    if (previewFilter === 'with') {
      list = list.filter((s) => Boolean(s.thumbnailDataUrl));
    } else if (previewFilter === 'without') {
      list = list.filter((s) => !s.thumbnailDataUrl);
    }
    const mult = sortOrder === 'newest' ? -1 : 1;
    return [...list].sort((a, b) => {
      const taRaw = Date.parse(a.createdAt as unknown as string);
      const tbRaw = Date.parse(b.createdAt as unknown as string);
      const ta = Number.isFinite(taRaw) ? taRaw : 0;
      const tb = Number.isFinite(tbRaw) ? tbRaw : 0;
      return mult * (ta - tb);
    });
  }, [snapshots, query, previewFilter, sortOrder]);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[1300] bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-[1301] flex max-h-[min(92vh,48rem)] w-[min(96vw,42rem)] min-h-0 -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-xl outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 dark:border-gray-700 dark:bg-gray-900"
        >
          <div className="flex shrink-0 items-start justify-between gap-3 border-b border-gray-200 px-4 py-3 dark:border-gray-700">
            <div className="flex min-w-0 items-start gap-2">
              <LayoutGrid className="mt-0.5 h-5 w-5 shrink-0 text-indigo-600 dark:text-indigo-400" aria-hidden />
              <div className="min-w-0">
                <Dialog.Title className="text-sm font-semibold text-gray-900 dark:text-white">
                  Quick snapshot gallery
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-xs leading-snug text-gray-500 dark:text-gray-400">
                  Search by summary, author, description, time, snapshot id, or layout counts. Filter by preview image.
                  Newest captures appear first by default.
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close
              type="button"
              className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>

          <div className="shrink-0 space-y-3 border-b border-gray-200 px-4 py-3 dark:border-gray-700">
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 dark:text-gray-500"
                aria-hidden
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search snapshots…"
                className="w-full rounded-lg border border-gray-200 bg-white py-2 pl-9 pr-3 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder:text-gray-500"
                aria-label="Search quick snapshots"
              />
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-4">
              <div className="flex min-w-0 flex-col gap-1.5 sm:flex-row sm:items-center">
                <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  Preview
                </span>
                <ToggleGroup.Root
                  type="single"
                  value={previewFilter}
                  onValueChange={(v) => v && setPreviewFilter(v as QuickSnapshotPreviewFilter)}
                  className="inline-flex flex-wrap gap-1 rounded-md border border-gray-200 bg-gray-50 p-1 dark:border-gray-600 dark:bg-gray-800"
                  aria-label="Filter by preview image"
                >
                  {(['all', 'with', 'without'] as const).map((v) => (
                    <ToggleGroup.Item
                      key={v}
                      value={v}
                      className="rounded px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 data-[state=on]:bg-indigo-100 data-[state=on]:text-indigo-800 dark:text-gray-300 dark:hover:bg-gray-700 dark:data-[state=on]:bg-indigo-900/50 dark:data-[state=on]:text-indigo-200"
                    >
                      {v === 'all' ? 'All' : v === 'with' ? 'With image' : 'No image'}
                    </ToggleGroup.Item>
                  ))}
                </ToggleGroup.Root>
              </div>
              <div className="flex min-w-0 flex-col gap-1.5 sm:flex-row sm:items-center">
                <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  Sort
                </span>
                <ToggleGroup.Root
                  type="single"
                  value={sortOrder}
                  onValueChange={(v) => v && setSortOrder(v as QuickSnapshotSortOrder)}
                  className="inline-flex gap-1 rounded-md border border-gray-200 bg-gray-50 p-1 dark:border-gray-600 dark:bg-gray-800"
                  aria-label="Sort order"
                >
                  <ToggleGroup.Item
                    value="newest"
                    className="rounded px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 data-[state=on]:bg-indigo-100 data-[state=on]:text-indigo-800 dark:text-gray-300 dark:hover:bg-gray-700 dark:data-[state=on]:bg-indigo-900/50 dark:data-[state=on]:text-indigo-200"
                  >
                    Newest
                  </ToggleGroup.Item>
                  <ToggleGroup.Item
                    value="oldest"
                    className="rounded px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 data-[state=on]:bg-indigo-100 data-[state=on]:text-indigo-800 dark:text-gray-300 dark:hover:bg-gray-700 dark:data-[state=on]:bg-indigo-900/50 dark:data-[state=on]:text-indigo-200"
                  >
                    Oldest
                  </ToggleGroup.Item>
                </ToggleGroup.Root>
              </div>
            </div>
            <p className="text-[11px] text-gray-500 dark:text-gray-400">
              Showing {filteredSorted.length} of {snapshots.length}
            </p>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3">
            {snapshots.length === 0 ? (
              <p className="text-sm text-gray-600 dark:text-gray-400">
                No quick snapshots yet. Use{' '}
                <span className="font-semibold text-gray-800 dark:text-gray-200">Capture</span> in the Layout panel.
              </p>
            ) : filteredSorted.length === 0 ? (
              <p className="text-sm text-gray-600 dark:text-gray-400">
                No snapshots match your search or filters. Try clearing the search box or setting the preview filter to{' '}
                <span className="font-semibold text-gray-800 dark:text-gray-200">All</span>.
              </p>
            ) : (
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {filteredSorted.map((s) => {
                  const caption = formatQuickSnapshotCaption(s.createdAt);
                  const countsLine = quickSnapshotCountsSummary(s);
                  const userSummary = s.summary?.trim();
                  const summaryLine = userSummary || countsLine;
                  const author = quickSnapshotAuthorDisplay(s);
                  const desc = s.description?.trim();
                  const titleParts = [
                    desc || undefined,
                    !restoreDisabled ? `Restore canvas from ${caption}` : restoreDisabledReason ?? 'Cannot restore',
                  ]
                    .filter(Boolean)
                    .join('\n\n');
                  return (
                    <li key={s.id} className="list-none">
                      <button
                        type="button"
                        disabled={restoreDisabled}
                        onClick={() => onRestore(s)}
                        aria-label={`Restore quick snapshot: ${summaryLine}, ${caption}`}
                        className={`w-full overflow-hidden rounded-lg border border-gray-200 bg-white text-left shadow-sm transition-opacity dark:border-gray-600 dark:bg-gray-800/70 ${
                          restoreDisabled
                            ? 'cursor-not-allowed opacity-50'
                            : 'hover:ring-2 hover:ring-indigo-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:hover:ring-indigo-500'
                        }`}
                        title={titleParts}
                      >
                        <div className="relative aspect-[5/3] w-full bg-gray-100 dark:bg-gray-900 pointer-events-none">
                          {s.thumbnailDataUrl ? (
                            <img
                              src={s.thumbnailDataUrl}
                              alt=""
                              className="absolute inset-0 h-full w-full object-cover"
                              loading="lazy"
                              decoding="async"
                            />
                          ) : (
                            <div
                              className="absolute inset-0 flex flex-col items-center justify-center gap-1 px-1 text-center text-gray-400 dark:text-gray-500"
                              role="img"
                              aria-label="No preview image for this snapshot"
                            >
                              <ImageIcon className="h-5 w-5 shrink-0 opacity-60" aria-hidden />
                              <span className="text-[9px] leading-tight">No preview</span>
                            </div>
                          )}
                        </div>
                        <div className="pointer-events-none border-t border-gray-100 px-2 py-1.5 dark:border-gray-700/80">
                          <p className="truncate text-[10px] font-medium tabular-nums text-gray-700 dark:text-gray-200">
                            {caption}
                          </p>
                          {author ? (
                            <p className="truncate text-[9px] text-gray-500 dark:text-gray-400">{author}</p>
                          ) : null}
                          <p className="truncate text-[9px] font-medium text-gray-700 dark:text-gray-200">{summaryLine}</p>
                          {userSummary ? (
                            <p className="truncate text-[9px] text-gray-500 dark:text-gray-400">{countsLine}</p>
                          ) : null}
                          {desc ? (
                            <p className="line-clamp-2 text-[9px] leading-tight text-gray-500 dark:text-gray-400">{desc}</p>
                          ) : null}
                          <p className="mt-0.5 truncate font-mono text-[9px] text-gray-400 dark:text-gray-500">{s.id}</p>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
