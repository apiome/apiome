'use client';

import * as React from 'react';
import * as Tooltip from '@radix-ui/react-tooltip';
import { Lock } from 'lucide-react';
import { cn } from '@lib/utils';
import { useDraftLockShared } from '@/app/ade/studio/hooks/useDraftLockShared';

export type { DraftLockStatusPayload } from '@/app/ade/studio/lib/studio-draft-lock-shared';

function formatRemaining(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '0s';
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function utcAbsoluteLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC');
}

export type DraftLockHeaderChipProps = {
  projectId: string;
  versionId: string;
  published: boolean;
  sessionUserId: string | undefined;
  className?: string;
};

export function DraftLockHeaderChip({
  projectId,
  versionId,
  published,
  sessionUserId,
  className,
}: DraftLockHeaderChipProps) {
  const { payload: remote, nowMs } = useDraftLockShared(projectId, versionId, published);

  if (published || !remote?.active || !remote?.ownerUserId || !remote?.expiresAt) {
    return null;
  }

  const remainingLabel = formatRemaining(new Date(remote.expiresAt).getTime() - nowMs);
  const absoluteLabel = utcAbsoluteLabel(remote.expiresAt);
  const ownerShort =
    remote.ownerUserId === sessionUserId ? 'You' : `${remote.ownerUserId.slice(0, 8)}…`;

  const tooltipLines = [
    `Locked by ${remote.ownerUserId === sessionUserId ? 'you' : remote.ownerUserId}`,
    `Expires: ${absoluteLabel}`,
    `Time left: ${remainingLabel}`,
  ];

  return (
    <Tooltip.Provider delayDuration={200}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <span
            tabIndex={0}
            data-testid="studio-draft-lock-chip"
            className={cn(
              'inline-flex rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-rose-400',
              className
            )}
          >
            <span
              role="status"
              aria-label={`Draft edit lock: ${ownerShort}, expires in ${remainingLabel}`}
              className="inline-flex items-center gap-1 rounded-md border border-rose-300/90 bg-rose-50 px-2 py-0.5 text-[11px] font-medium tabular-nums leading-tight text-rose-950 dark:border-rose-700/80 dark:bg-rose-950/40 dark:text-rose-50"
            >
              <Lock className="h-3 w-3 shrink-0" aria-hidden />
              Lock · {ownerShort} · {remainingLabel}
            </span>
          </span>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            className="z-[10002] max-w-xs rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-800 shadow-md dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            sideOffset={4}
          >
            <div className="space-y-0.5">
              {tooltipLines.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
            </div>
            <Tooltip.Arrow className="fill-white dark:fill-gray-800" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
