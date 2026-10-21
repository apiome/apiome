'use client';

/**
 * The Profile page's **Favorite projects** card (#542).
 *
 * A reader's favorites *are* their pinned projects (#513): one list, kept per person on the
 * server, pinned from a project's ⋯ menu on **Projects**. Home shows it as "Pinned projects";
 * this card shows the same list on the profile — where the original request asked for it — with
 * the same open and unpin controls, and the command palette offers it as **Favorites**.
 *
 * The list is drawn by Home's {@link PinnedProjects} panel under this card's own heading, so the
 * two cannot drift in rows, empty state or unpin behaviour.
 */

import * as React from 'react';

import { PinnedProjects } from '@/app/components/ade/dashboard/home/PinnedProjects';
import type { PinnedProject } from '@lib/db/dashboard-home-model';
import { listPinnedProjectsForSession } from '@lib/db/project-pins';
import { useUnpinProject } from '@/app/hooks/useUnpinProject';

/** The card's heading, named once so the page and its tests agree. */
export const FAVORITES_HEADING = {
  title: 'Favorite projects',
  subtitle: 'Pinned to Home and listed in ⌘K',
} as const;

/** Props for {@link FavoriteProjectsCard}. */
export interface FavoriteProjectsCardProps {
  /**
   * The current workspace. Favorites are per workspace, so the list is re-read when it changes;
   * with none, the card shows its empty state without a read.
   */
  tenantId?: string | null;
}

/**
 * Load the reader's favorites and draw them.
 *
 * @param props See {@link FavoriteProjectsCardProps}.
 * @returns The card.
 */
export function FavoriteProjectsCard({ tenantId }: FavoriteProjectsCardProps) {
  const [favorites, setFavorites] = React.useState<PinnedProject[]>([]);
  const [loadedFor, setLoadedFor] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!tenantId) return;
    let cancelled = false;
    void listPinnedProjectsForSession()
      .catch(() => [] as PinnedProject[])
      .then((pins) => {
        if (cancelled) return;
        setFavorites(pins);
        setLoadedFor(tenantId);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const { unpinning, unpin } = useUnpinProject(favorites, setFavorites);

  // Loading until this workspace's read lands; no workspace means nothing to load.
  const loading = Boolean(tenantId) && loadedFor !== tenantId;

  return (
    <PinnedProjects
      projects={tenantId ? favorites : []}
      loading={loading}
      onUnpin={(project) => void unpin(project)}
      unpinning={unpinning}
      heading={FAVORITES_HEADING}
      testId="profile-favorites"
    />
  );
}

export default FavoriteProjectsCard;
