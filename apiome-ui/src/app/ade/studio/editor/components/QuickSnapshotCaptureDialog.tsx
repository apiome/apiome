'use client';

import React, { useEffect, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Camera, X } from 'lucide-react';
import {
  QUICK_SNAPSHOT_DESCRIPTION_MAX_LEN,
  QUICK_SNAPSHOT_SUMMARY_MAX_LEN,
} from '../lib/quick-layout-snapshots';

export interface QuickSnapshotCaptureDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Shown read-only; stored on the snapshot as author. */
  authorLabel: string;
  isSaving: boolean;
  onConfirm: (meta: { summary: string; description: string }) => void;
}

export function QuickSnapshotCaptureDialog({
  open,
  onOpenChange,
  authorLabel,
  isSaving,
  onConfirm,
}: QuickSnapshotCaptureDialogProps) {
  const [summary, setSummary] = useState('');
  const [description, setDescription] = useState('');
  const [summaryError, setSummaryError] = useState<string | undefined>();

  useEffect(() => {
    if (!open) {
      setSummary('');
      setDescription('');
      setSummaryError(undefined);
    }
  }, [open]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = summary.trim();
    if (!trimmed) {
      setSummaryError('Enter a short summary for this snapshot.');
      return;
    }
    setSummaryError(undefined);
    onConfirm({
      summary: trimmed.slice(0, QUICK_SNAPSHOT_SUMMARY_MAX_LEN),
      description: description.trim().slice(0, QUICK_SNAPSHOT_DESCRIPTION_MAX_LEN),
    });
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[1300] bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-[1301] w-[min(96vw,26rem)] max-h-[min(92vh,32rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-gray-200 bg-white p-0 shadow-xl outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 dark:border-gray-700 dark:bg-gray-900"
        >
          <div className="flex items-start justify-between gap-3 border-b border-gray-200 px-4 py-3 dark:border-gray-700">
            <div className="flex min-w-0 items-start gap-2">
              <Camera className="mt-0.5 h-5 w-5 shrink-0 text-indigo-600 dark:text-indigo-400" aria-hidden />
              <div className="min-w-0">
                <Dialog.Title className="text-sm font-semibold text-gray-900 dark:text-white">
                  Capture quick snapshot
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-xs leading-snug text-gray-500 dark:text-gray-400">
                  Add a summary and optional description. Timestamp and canvas capture run when you save.
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close
              type="button"
              disabled={isSaving}
              className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>

          <form onSubmit={handleSubmit} className="space-y-3 px-4 py-3">
            <div>
              <p className="text-[11px] font-medium text-gray-600 dark:text-gray-300">
                Author{' '}
                <span className="font-normal text-gray-500 dark:text-gray-400">(stored with this capture)</span>
              </p>
              <p className="mt-0.5 truncate text-sm text-gray-900 dark:text-gray-100">{authorLabel}</p>
            </div>

            <div>
              <label htmlFor="quick-snapshot-summary" className="text-[11px] font-medium text-gray-600 dark:text-gray-300">
                Summary <span className="text-red-600 dark:text-red-400">*</span>
              </label>
              <input
                id="quick-snapshot-summary"
                type="text"
                value={summary}
                onChange={(e) => {
                  setSummary(e.target.value.slice(0, QUICK_SNAPSHOT_SUMMARY_MAX_LEN));
                  if (summaryError) setSummaryError(undefined);
                }}
                disabled={isSaving}
                maxLength={QUICK_SNAPSHOT_SUMMARY_MAX_LEN}
                placeholder="e.g. Before refactoring auth flow"
                className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder:text-gray-500"
                aria-invalid={Boolean(summaryError)}
                aria-describedby={summaryError ? 'quick-snapshot-summary-error' : undefined}
                autoComplete="off"
              />
              <div className="mt-0.5 flex justify-between gap-2 text-[10px] text-gray-400 dark:text-gray-500">
                {summaryError ? (
                  <span id="quick-snapshot-summary-error" className="text-red-600 dark:text-red-400">
                    {summaryError}
                  </span>
                ) : (
                  <span />
                )}
                <span>
                  {summary.length}/{QUICK_SNAPSHOT_SUMMARY_MAX_LEN}
                </span>
              </div>
            </div>

            <div>
              <label htmlFor="quick-snapshot-description" className="text-[11px] font-medium text-gray-600 dark:text-gray-300">
                Description <span className="font-normal text-gray-500">(optional)</span>
              </label>
              <textarea
                id="quick-snapshot-description"
                value={description}
                onChange={(e) => setDescription(e.target.value.slice(0, QUICK_SNAPSHOT_DESCRIPTION_MAX_LEN))}
                disabled={isSaving}
                rows={3}
                placeholder="Context or notes for your future self…"
                className="mt-1 w-full resize-y rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder:text-gray-500"
              />
              <p className="mt-0.5 text-right text-[10px] text-gray-400 dark:text-gray-500">
                {description.length}/{QUICK_SNAPSHOT_DESCRIPTION_MAX_LEN}
              </p>
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <Dialog.Close asChild>
                <button
                  type="button"
                  disabled={isSaving}
                  className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                >
                  Cancel
                </button>
              </Dialog.Close>
              <button
                type="submit"
                disabled={isSaving}
                className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-400"
              >
                {isSaving ? 'Capturing…' : 'Save snapshot'}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
