'use client';

import type { ReactNode } from 'react';
import * as Tooltip from '@radix-ui/react-tooltip';
import { ArrowUp, Circle, GitCompareArrows } from 'lucide-react';
import { cn } from '@lib/utils';

export type StudioSyncStatusChipsProps = {
  localDirty: boolean;
  authoredRevisionCount: number;
  serverAhead: boolean;
  className?: string;
};

function Chip({
  children,
  className,
  title,
  'aria-label': ariaLabel,
}: {
  children: ReactNode;
  className?: string;
  title: string;
  'aria-label'?: string;
}) {
  return (
    <span
      role="status"
      title={title}
      aria-label={ariaLabel ?? title}
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium tabular-nums leading-tight',
        className
      )}
    >
      {children}
    </span>
  );
}

export function StudioSyncStatusChips({
  localDirty,
  authoredRevisionCount,
  serverAhead,
  className,
}: StudioSyncStatusChipsProps) {
  const showAuthoredRevisions = authoredRevisionCount > 0;

  if (!localDirty && !showAuthoredRevisions && !serverAhead) {
    return null;
  }

  return (
    <Tooltip.Provider delayDuration={200}>
      <div
        className={cn('flex flex-wrap items-center gap-1.5 shrink-0', className)}
        aria-label="Sync status"
      >
        {localDirty ? (
          <Tooltip.Root>
            <Tooltip.Trigger asChild>
              <span tabIndex={0} className="rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-amber-400">
                <Chip
                  title="Unsaved canvas changes (layout auto-save pending or in progress)."
                  aria-label="Dirty: unsaved local changes"
                  className="border-amber-300/90 bg-amber-50 text-amber-950 dark:border-amber-700/80 dark:bg-amber-950/35 dark:text-amber-50"
                >
                  <Circle className="h-3 w-3 fill-current opacity-90" aria-hidden />
                  Dirty
                </Chip>
              </span>
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content
                className="z-[10002] max-w-xs rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-800 shadow-md dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
                sideOffset={4}
              >
                Unsaved local edits — wait for auto-save or save layout before switching away if needed.
                <Tooltip.Arrow className="fill-white dark:fill-gray-800" />
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
        ) : null}

        {showAuthoredRevisions ? (
          <Tooltip.Root>
            <Tooltip.Trigger asChild>
              <span tabIndex={0} className="rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-slate-400">
                <Chip
                  title="Revisions you authored between this selection and the latest revision (main lineage)."
                  aria-label={`Your authored revisions between this selection and head: ${authoredRevisionCount}`}
                  className="border-slate-300/90 bg-slate-50 text-slate-900 dark:border-slate-600 dark:bg-slate-800/80 dark:text-slate-100"
                >
                  <ArrowUp className="h-3 w-3" aria-hidden />
                  {authoredRevisionCount}
                </Chip>
              </span>
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content
                className="z-[10002] max-w-xs rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-800 shadow-md dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
                sideOffset={4}
              >
                Your commits on the path from latest to this revision — move to the latest revision to
                continue from head.
                <Tooltip.Arrow className="fill-white dark:fill-gray-800" />
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
        ) : null}

        {serverAhead ? (
          <Tooltip.Root>
            <Tooltip.Trigger asChild>
              <span tabIndex={0} className="rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-violet-400">
                <Chip
                  title="The project has a newer revision than your selection, or the server rejected a push as stale."
                  aria-label="Server ahead: newer revision available or push base stale"
                  className="border-violet-300/90 bg-violet-50 text-violet-950 dark:border-violet-700/80 dark:bg-violet-950/40 dark:text-violet-50"
                >
                  <GitCompareArrows className="h-3 w-3" aria-hidden />
                  Ahead
                </Chip>
              </span>
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content
                className="z-[10002] max-w-xs rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-800 shadow-md dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
                sideOffset={4}
              >
                Pull or select the latest revision before committing, or resolve the server-ahead banner
                if you hit a stale push.
                <Tooltip.Arrow className="fill-white dark:fill-gray-800" />
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
        ) : null}
      </div>
    </Tooltip.Provider>
  );
}
