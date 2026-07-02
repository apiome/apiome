'use client';

import { useEffect, useSyncExternalStore } from 'react';
import {
  acquireDraftLockShared,
  getDraftLockSharedSnapshot,
  releaseDraftLockShared,
  subscribeDraftLockShared,
  type DraftLockSharedSnapshot,
} from '@/app/ade/studio/lib/studio-draft-lock-shared';

export function useDraftLockShared(
  projectId: string | null | undefined,
  versionId: string | null | undefined,
  published: boolean
): DraftLockSharedSnapshot {
  const snap = useSyncExternalStore(subscribeDraftLockShared, getDraftLockSharedSnapshot, getDraftLockSharedSnapshot);

  useEffect(() => {
    if (!projectId || !versionId || published) return;
    acquireDraftLockShared(projectId, versionId, false);
    return () => releaseDraftLockShared(projectId, versionId, false);
  }, [projectId, versionId, published]);

  return snap;
}
