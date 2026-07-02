'use client';

/**
 * Compact branch list for the git dropdown side submenu (checkout + new branch).
 * Replaces the separate toolbar branch popover (#2722 GLI-03).
 */

import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { GitBranch, Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react';
import { toast } from 'sonner';
import { useStudio } from '../StudioContext';
import { Spinner } from '@/app/components/ui/Spinner';
import type { VersionBranchRow } from '@/app/components/ade/version-dialogs/types';
import type { Version } from '../editor/components/types';
import { sortBranchesForPicker } from '@/app/ade/studio/lib/studio-branch-resolve';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/app/components/ui/AlertDialog';

export type BranchSwitchSubmenuProps = {
  versions: Version[];
  setVersions: Dispatch<SetStateAction<Version[]>>;
  itemClass: string;
};

export function BranchSwitchSubmenu({ versions, setVersions, itemClass }: BranchSwitchSubmenuProps) {
  const {
    selectedProjectId,
    selectedVersionId,
    setSelectedVersionId,
    setSelectedBranchId,
    selectedBranchId,
    setIsReadOnly,
    triggerCanvasRefresh,
    triggerSidebarRefresh,
    syncLocalDirty,
    setVersionBranchesForProject,
    openBranchFromRevisionDialog,
  } = useStudio();

  const [loading, setLoading] = useState(false);
  const [list, setList] = useState<VersionBranchRow[]>([]);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [pendingCheckout, setPendingCheckout] = useState<VersionBranchRow | null>(null);

  const sortedBranches = useMemo(() => sortBranchesForPicker(list), [list]);

  const refreshVersions = useCallback(async (): Promise<Version[] | null> => {
    if (!selectedProjectId) return null;
    try {
      const response = await fetch(`/api/versions?projectId=${encodeURIComponent(selectedProjectId)}`);
      const result = await response.json();
      if (!response.ok || !result.success || !Array.isArray(result.versions)) {
        return null;
      }
      const next = result.versions as Version[];
      setVersions(next);
      return next;
    } catch {
      return null;
    }
  }, [selectedProjectId, setVersions]);

  const loadBranches = useCallback(async () => {
    if (!selectedProjectId) return;
    setLoading(true);
    setFetchError(null);
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(selectedProjectId)}/version-branches`);
      const d = (await r.json()) as {
        success?: boolean;
        branches?: VersionBranchRow[];
        error?: string;
      };
      if (!r.ok || !d.success || !Array.isArray(d.branches)) {
        setFetchError(typeof d.error === 'string' ? d.error : 'Could not load branches');
        setList([]);
        return;
      }
      const sorted = sortBranchesForPicker(d.branches);
      setList(sorted);
      setVersionBranchesForProject(selectedProjectId, d.branches);
    } catch {
      setFetchError('Could not load branches');
      setList([]);
    } finally {
      setLoading(false);
    }
  }, [selectedProjectId, setVersionBranchesForProject]);

  useEffect(() => {
    void loadBranches();
  }, [loadBranches]);

  const performCheckout = useCallback(
    async (branch: VersionBranchRow) => {
      if (!selectedProjectId) return;
      const tipId = branch.tip_version_id;
      if (String(tipId) === String(selectedVersionId)) {
        return;
      }
      let nextVersions = versions;
      let tip = versions.find((v) => String(v.id) === String(tipId));
      if (!tip) {
        const refreshed = await refreshVersions();
        if (refreshed) nextVersions = refreshed;
        tip = nextVersions.find((v) => String(v.id) === String(tipId));
      }
      if (!tip) {
        toast.error('Branch tip revision is not available in this session. Refresh the revision list.');
        return;
      }
      setSelectedVersionId(tipId);
      setSelectedBranchId(branch.id);
      setIsReadOnly(tip.published ?? false);
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(selectedProjectId)}/version-branches`);
        if (r.ok) {
          const d = (await r.json()) as { success?: boolean; branches?: VersionBranchRow[] };
          if (d.success && Array.isArray(d.branches)) {
            setVersionBranchesForProject(selectedProjectId, d.branches);
          }
        }
      } catch {
        /* best-effort */
      }
      triggerCanvasRefresh();
      triggerSidebarRefresh();
      toast.success(`Checked out ${branch.name}`);
    },
    [
      selectedProjectId,
      selectedVersionId,
      versions,
      refreshVersions,
      setSelectedVersionId,
      setSelectedBranchId,
      setIsReadOnly,
      setVersionBranchesForProject,
      triggerCanvasRefresh,
      triggerSidebarRefresh,
    ]
  );

  const requestCheckout = useCallback(
    (branch: VersionBranchRow) => {
      if (String(branch.tip_version_id) === String(selectedVersionId)) {
        return;
      }
      if (syncLocalDirty) {
        setPendingCheckout(branch);
        return;
      }
      void performCheckout(branch);
    },
    [syncLocalDirty, selectedVersionId, performCheckout]
  );

  return (
    <>
      {loading && (
        <div className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-300">
          <Spinner size="sm" className="shrink-0" aria-hidden />
          Loading…
        </div>
      )}
      {!loading && fetchError && (
        <div className="px-3 py-2 text-sm text-red-600 dark:text-red-400">{fetchError}</div>
      )}
      {!loading && !fetchError && sortedBranches.length === 0 && (
        <div className="px-3 py-2 text-xs text-gray-500 dark:text-gray-400">No branches yet.</div>
      )}
      {!loading &&
        !fetchError &&
        sortedBranches.map((b) => {
          const atTip = String(b.tip_version_id) === String(selectedVersionId);
          const isSel = selectedBranchId === b.id;
          return (
            <DropdownMenu.Item
              key={b.id}
              className={itemClass}
              disabled={atTip}
              onSelect={() => {
                requestCheckout(b);
              }}
            >
              <GitBranch className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
              <span className="min-w-0 flex-1 truncate">
                {b.name}
                {b.is_default ? (
                  <span className="ml-1.5 text-[10px] font-medium uppercase text-gray-500 dark:text-gray-400">
                    default
                  </span>
                ) : null}
              </span>
              {isSel ? (
                <span className="shrink-0 text-[10px] text-gray-500 dark:text-gray-400">current</span>
              ) : null}
            </DropdownMenu.Item>
          );
        })}

      <DropdownMenu.Separator className="my-1 h-px bg-gray-100 dark:bg-gray-700" />

      <DropdownMenu.Item
        className={itemClass}
        onSelect={() => {
          openBranchFromRevisionDialog();
        }}
      >
        <Plus className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
        <span className="flex-1">New branch…</span>
      </DropdownMenu.Item>

      <AlertDialog open={pendingCheckout !== null} onOpenChange={(o) => !o && setPendingCheckout(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Unsaved layout changes</AlertDialogTitle>
            <AlertDialogDescription>
              Switching branches will reload the canvas from the branch tip and you may lose unsaved canvas layout
              changes. Continue?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const b = pendingCheckout;
                setPendingCheckout(null);
                if (b) void performCheckout(b);
              }}
            >
              Switch branch
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
