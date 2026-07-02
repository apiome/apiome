'use client';

import { useEffect } from 'react';
import type { VersionBranchRow } from '@/app/components/ade/version-dialogs/types';
import { resolveActiveBranchForRevision } from '@/app/ade/studio/lib/studio-branch-resolve';

/**
 * Loads named branches when the studio project changes and keeps `selectedBranchId`
 * aligned with the current revision when it matches a branch tip (#2722).
 */
export function useStudioBranchSync(options: {
  projectId: string;
  revisionId: string;
  versionBranchesByProjectId: Record<string, VersionBranchRow[]>;
  setVersionBranchesForProject: (projectId: string, branches: VersionBranchRow[]) => void;
  setSelectedBranchId: (id: string | null) => void;
}): void {
  const {
    projectId,
    revisionId,
    versionBranchesByProjectId,
    setVersionBranchesForProject,
    setSelectedBranchId,
  } = options;

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/version-branches`);
        const d = (await r.json()) as {
          success?: boolean;
          branches?: VersionBranchRow[];
        };
        if (cancelled || !r.ok || !d.success || !Array.isArray(d.branches)) return;
        setVersionBranchesForProject(projectId, d.branches);
      } catch {
        /* branch chip will retry on open */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, setVersionBranchesForProject]);

  useEffect(() => {
    if (!projectId || !revisionId) {
      setSelectedBranchId(null);
      return;
    }
    const branches = versionBranchesByProjectId[projectId];
    if (!branches?.length) return;
    const row = resolveActiveBranchForRevision(revisionId, branches);
    setSelectedBranchId(row?.id ?? null);
  }, [projectId, revisionId, versionBranchesByProjectId, setSelectedBranchId]);
}
