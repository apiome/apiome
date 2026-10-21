'use client';

/**
 * Optimistic unpinning for a list of pinned projects (#513, #542).
 *
 * Home's **Pinned projects** panel and the Profile page's **Favorite projects** card both draw
 * the reader's pins with an unpin button per row. Both behave the same way: the row goes at once,
 * and comes back in its old place with an error toast if the write fails — a list that waited on
 * the round trip would feel broken on a slow link.
 */

import { useCallback, useState } from 'react';

import { toast } from '@/app/components/ui/toast';
import type { PinnedProject } from '@lib/db/dashboard-home-model';
import { unpinProjectForSession } from '@lib/db/project-pins';

/** What {@link useUnpinProject} returns. */
export interface UseUnpinProjectResult {
  /** Ids of projects whose unpin is in flight — their buttons go inert. */
  unpinning: ReadonlySet<string>;
  /** Unpin one project from the list. */
  unpin: (project: PinnedProject) => Promise<void>;
}

/**
 * Unpin projects from a list the caller owns.
 *
 * @param pins The list as drawn now; restored as-is if the write fails.
 * @param setPins Replace the list.
 * @returns See {@link UseUnpinProjectResult}.
 */
export function useUnpinProject(
  pins: readonly PinnedProject[],
  setPins: (next: PinnedProject[]) => void,
): UseUnpinProjectResult {
  const [unpinning, setUnpinning] = useState<ReadonlySet<string>>(() => new Set());

  const unpin = useCallback(
    async (project: PinnedProject) => {
      const before = [...pins];
      setUnpinning((current) => new Set(current).add(project.projectId));
      setPins(before.filter((pin) => pin.projectId !== project.projectId));

      const ok = await unpinProjectForSession(project.projectId).catch(() => false);
      if (ok) {
        toast.success(`Unpinned "${project.projectName}".`);
      } else {
        setPins(before);
        toast.error(`Could not unpin "${project.projectName}". Try again.`);
      }
      setUnpinning((current) => {
        const next = new Set(current);
        next.delete(project.projectId);
        return next;
      });
    },
    [pins, setPins],
  );

  return { unpinning, unpin };
}

export default useUnpinProject;
