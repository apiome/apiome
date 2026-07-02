'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import * as ToggleGroup from '@radix-ui/react-toggle-group';
import { X, LayoutGrid, Search, Image as ImageIcon, Share2, Upload, Pin } from 'lucide-react';
import {
  formatQuickSnapshotCaption,
  quickSnapshotAuthorDisplay,
  quickSnapshotCountsSummary,
  quickSnapshotMatchesSearch,
  stringifyQuickLayoutShareEnvelope,
  type QuickLayoutSnapshot,
} from '../lib/quick-layout-snapshots';

export type QuickSnapshotPreviewFilter = 'all' | 'with' | 'without';
export type QuickSnapshotSortOrder = 'newest' | 'oldest';

export type QuickSnapshotGalleryAlertVariant = 'success' | 'error' | 'warning' | 'info';

export type ImportSharedQuickSnapshotResult =
  | { success: true }
  | { success: false; message: string };

export interface QuickSnapshotGalleryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  snapshots: QuickLayoutSnapshot[];
  onRestore: (snapshot: QuickLayoutSnapshot) => void;
  restoreDisabled: boolean;
  /** Shown as title/tooltip when restore is disabled (e.g. read-only). */
  restoreDisabledReason?: string;
  /** Current API version id — required to build share JSON and validate imports. */
  versionId: string | null;
  /** Persist a shared JSON envelope; return success or an error message for the user. */
  onImportSharedJson: (jsonText: string) => Promise<ImportSharedQuickSnapshotResult>;
  alertDialog: (opts: { message: string; variant: QuickSnapshotGalleryAlertVariant }) => Promise<void>;
  /** Tenant admins can pin a snapshot as the team default for this API version (shared named layout + tenant preference). */
  pinTeamDefaultEnabled?: boolean;
  onPinTeamDefault?: (snapshot: QuickLayoutSnapshot) => void | Promise<void>;
}

export function QuickSnapshotGalleryDialog({
  open,
  onOpenChange,
  snapshots,
  onRestore,
  restoreDisabled,
  restoreDisabledReason,
  versionId,
  onImportSharedJson,
  alertDialog,
  pinTeamDefaultEnabled = false,
  onPinTeamDefault,
}: QuickSnapshotGalleryDialogProps) {
  const [query, setQuery] = useState('');
  const [previewFilter, setPreviewFilter] = useState<QuickSnapshotPreviewFilter>('all');
  const [sortOrder, setSortOrder] = useState<QuickSnapshotSortOrder>('newest');
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState('');
  const [importBusy, setImportBusy] = useState(false);
  const importFileRef = useRef<HTMLInputElement>(null);

  const shareEnabled = Boolean(versionId?.trim());

  const copyShareJson = useCallback(
    async (snapshot: QuickLayoutSnapshot) => {
      if (!shareEnabled || !versionId) {
        await alertDialog({ message: 'Open a version to share snapshots.', variant: 'warning' });
        return;
      }
      try {
        const text = stringifyQuickLayoutShareEnvelope(versionId, snapshot);
        await navigator.clipboard.writeText(text);
        await alertDialog({
          message:
            'Snapshot JSON copied. Paste it into chat or a file for teammates; they can import it from this gallery for this API version.',
          variant: 'success',
        });
      } catch (e) {
        console.error('Quick snapshot share copy failed:', e);
        await alertDialog({ message: 'Could not copy to the clipboard.', variant: 'error' });
      }
    },
    [alertDialog, shareEnabled, versionId]
  );

  const downloadShareJson = useCallback(
    async (snapshot: QuickLayoutSnapshot) => {
      if (!shareEnabled || !versionId) {
        await alertDialog({ message: 'Open a version to share snapshots.', variant: 'warning' });
        return;
      }
      try {
        const text = stringifyQuickLayoutShareEnvelope(versionId, snapshot);
        const safeId = snapshot.id.replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 12) || 'snapshot';
        const blob = new Blob([text], { type: 'application/json;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `apiome-quick-snapshot-${safeId}.json`;
        a.rel = 'noopener';
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 2_000);
      } catch (e) {
        console.error('Quick snapshot share download failed:', e);
        await alertDialog({ message: 'Could not start the download.', variant: 'error' });
      }
    },
    [alertDialog, shareEnabled, versionId]
  );

  const runImport = useCallback(async () => {
    setImportBusy(true);
    try {
      const result = await onImportSharedJson(importText);
      if (result.success) {
        await alertDialog({ message: 'Shared snapshot added to your gallery.', variant: 'success' });
        setImportOpen(false);
        setImportText('');
      } else {
        await alertDialog({ message: result.message, variant: 'error' });
      }
    } catch (e) {
      console.error('Import shared quick snapshot failed:', e);
      await alertDialog({ message: 'Could not import the snapshot.', variant: 'error' });
    } finally {
      setImportBusy(false);
    }
  }, [alertDialog, importText, onImportSharedJson]);

  useEffect(() => {
    if (!open) {
      setQuery('');
      setPreviewFilter('all');
      setSortOrder('newest');
      setImportOpen(false);
      setImportText('');
      setImportBusy(false);
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
                  Newest captures appear first by default. Use Share on a tile to copy or download JSON for teammates on this
                  version; Import adds a shared file or pasted JSON to your local gallery. Tenant administrators can pin a
                  snapshot as the team default from the Share menu (saves a shared named layout for this version).
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
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={!shareEnabled}
                onClick={() => setImportOpen(true)}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                  shareEnabled
                    ? 'border-indigo-200 bg-indigo-50 text-indigo-800 hover:bg-indigo-100 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-200 dark:hover:bg-indigo-900/50'
                    : 'cursor-not-allowed border-gray-200 bg-gray-100 text-gray-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-500'
                }`}
                title={shareEnabled ? 'Add a snapshot shared by a teammate (same API version)' : 'Open a version first'}
              >
                <Upload className="h-3.5 w-3.5 shrink-0" aria-hidden />
                Import shared snapshot
              </button>
            </div>
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
                      <div
                        className={`relative overflow-hidden rounded-lg border border-gray-200 bg-white text-left shadow-sm dark:border-gray-600 dark:bg-gray-800/70 ${
                          restoreDisabled ? 'opacity-50' : ''
                        }`}
                      >
                        <div className="relative">
                          {shareEnabled ? (
                            <DropdownMenu.Root>
                              <DropdownMenu.Trigger asChild>
                                <button
                                  type="button"
                                  className="absolute right-1 top-1 z-10 flex h-7 w-7 items-center justify-center rounded-md border border-gray-200/90 bg-white/95 text-gray-700 shadow-sm hover:bg-white focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:border-gray-600 dark:bg-gray-900/95 dark:text-gray-200 dark:hover:bg-gray-800"
                                  aria-label={`Share snapshot: ${summaryLine}`}
                                  title="Copy or download JSON for teammates"
                                  onPointerDown={(e) => e.stopPropagation()}
                                >
                                  <Share2 className="h-3.5 w-3.5" aria-hidden />
                                </button>
                              </DropdownMenu.Trigger>
                              <DropdownMenu.Portal>
                                <DropdownMenu.Content
                                  className="z-[1400] min-w-[10rem] overflow-hidden rounded-md border border-gray-200 bg-white p-1 text-sm shadow-lg dark:border-gray-600 dark:bg-gray-900"
                                  sideOffset={4}
                                  align="end"
                                >
                                  <DropdownMenu.Item
                                    className="cursor-pointer rounded px-2 py-1.5 outline-none hover:bg-gray-100 focus:bg-gray-100 dark:hover:bg-gray-800 dark:focus:bg-gray-800"
                                    onSelect={() => void copyShareJson(s)}
                                  >
                                    Copy JSON
                                  </DropdownMenu.Item>
                                  <DropdownMenu.Item
                                    className="cursor-pointer rounded px-2 py-1.5 outline-none hover:bg-gray-100 focus:bg-gray-100 dark:hover:bg-gray-800 dark:focus:bg-gray-800"
                                    onSelect={() => void downloadShareJson(s)}
                                  >
                                    Download JSON
                                  </DropdownMenu.Item>
                                  {pinTeamDefaultEnabled && onPinTeamDefault ? (
                                    <DropdownMenu.Item
                                      className="cursor-pointer rounded px-2 py-1.5 outline-none hover:bg-gray-100 focus:bg-gray-100 dark:hover:bg-gray-800 dark:focus:bg-gray-800"
                                      onSelect={() => void onPinTeamDefault(s)}
                                    >
                                      <span className="flex items-center gap-2">
                                        <Pin className="h-3.5 w-3.5 shrink-0" aria-hidden />
                                        Pin as team default
                                      </span>
                                    </DropdownMenu.Item>
                                  ) : null}
                                </DropdownMenu.Content>
                              </DropdownMenu.Portal>
                            </DropdownMenu.Root>
                          ) : null}
                          <button
                            type="button"
                            disabled={restoreDisabled}
                            onClick={() => onRestore(s)}
                            aria-label={`Restore quick snapshot: ${summaryLine}, ${caption}`}
                            className={`w-full overflow-hidden text-left ${
                              restoreDisabled
                                ? 'cursor-not-allowed'
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
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Dialog.Content>

        <Dialog.Root open={importOpen} onOpenChange={setImportOpen}>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-[1302] bg-black/60 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
            <Dialog.Content
              className="fixed left-1/2 top-1/2 z-[1303] w-[min(96vw,24rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-gray-200 bg-white p-4 shadow-xl outline-none dark:border-gray-700 dark:bg-gray-900"
              onPointerDownOutside={(e) => {
                if (importBusy) e.preventDefault();
              }}
              onEscapeKeyDown={(e) => {
                if (importBusy) e.preventDefault();
              }}
            >
              <Dialog.Title className="text-sm font-semibold text-gray-900 dark:text-white">
                Import shared snapshot
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Paste JSON from a teammate (same API version) or choose a{' '}
                <code className="rounded bg-gray-100 px-0.5 text-[10px] dark:bg-gray-800">.json</code> file.
              </Dialog.Description>
              <textarea
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
                rows={8}
                className="mt-3 w-full rounded-lg border border-gray-200 bg-white px-2 py-1.5 font-mono text-[11px] text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
                placeholder='{ "kind": "apiome.quickLayoutSnapshotShare", ... }'
                disabled={importBusy}
                aria-label="Shared snapshot JSON"
              />
              <input
                ref={importFileRef}
                type="file"
                accept="application/json,.json"
                className="sr-only"
                aria-hidden
                tabIndex={-1}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = '';
                  if (!file) return;
                  const reader = new FileReader();
                  reader.onload = () => {
                    const text = typeof reader.result === 'string' ? reader.result : '';
                    setImportText(text);
                  };
                  reader.readAsText(file);
                }}
              />
              <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
                <button
                  type="button"
                  disabled={importBusy}
                  onClick={() => importFileRef.current?.click()}
                  className="mr-auto rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                >
                  Choose file…
                </button>
                <button
                  type="button"
                  disabled={importBusy}
                  onClick={() => {
                    setImportOpen(false);
                    setImportText('');
                  }}
                  className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={importBusy || !importText.trim()}
                  onClick={() => void runImport()}
                  className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {importBusy ? 'Importing…' : 'Import'}
                </button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
