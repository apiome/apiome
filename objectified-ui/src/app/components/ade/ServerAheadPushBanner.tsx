'use client';

import { AlertTriangle } from 'lucide-react';
import { Button } from '@/app/components/ui/Button';

type ServerAheadPushBannerProps = {
  /** Optional API detail (shown under the main line). */
  detail?: string;
  pullDisabled?: boolean;
  pullLoading?: boolean;
  onPull: () => void;
  onOpenMerge: () => void;
};

export default function ServerAheadPushBanner({
  detail,
  pullDisabled,
  pullLoading,
  onPull,
  onOpenMerge,
}: ServerAheadPushBannerProps) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300/90 bg-amber-50 px-4 py-3 text-sm text-amber-950 dark:border-amber-600/80 dark:bg-amber-950/40 dark:text-amber-50"
    >
      <div className="flex min-w-0 flex-1 items-start gap-2">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-700 dark:text-amber-400" aria-hidden />
        <span className="min-w-0 leading-snug">
          <span className="font-medium">Server has new changes.</span> Pull to integrate or open merge.
          {detail ? (
            <span className="mt-1 block text-xs opacity-90">{detail}</span>
          ) : null}
        </span>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={pullDisabled || pullLoading}
          onClick={onPull}
          className="border-amber-400/80 bg-white text-amber-950 hover:bg-amber-100 dark:border-amber-600 dark:bg-amber-900/50 dark:text-amber-50 dark:hover:bg-amber-900"
        >
          {pullLoading ? 'Pulling…' : 'Pull'}
        </Button>
        <Button type="button" variant="default" size="sm" onClick={onOpenMerge}>
          Open merge
        </Button>
      </div>
    </div>
  );
}
