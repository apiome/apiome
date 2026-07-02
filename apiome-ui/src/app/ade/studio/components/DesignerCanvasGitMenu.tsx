'use client';

/**
 * Floating git menu on the studio canvas.
 *
 * Canvas parity: every git-like action that used to require navigating to the Versions
 * dashboard now opens a Radix dialog in-place. Sections mirror the mental model of git:
 *   • This revision — Commit, Tag, Compare-with-parent (branch switch lives in submenu)
 *   • Branching     — Merge, Rollback
 *   • History/Sync  — History graph, Switch-to-latest (pull), Refresh, Open dashboard
 */

import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from 'react';
import { toast } from 'sonner';
import {
  ArrowDownToLine,
  Download,
  ExternalLink,
  FileSearch,
  ChevronRight,
  GitBranch,
  GitCompareArrows,
  GitCommit,
  GitMerge,
  History,
  RefreshCw,
  Tag,
  Undo2,
} from 'lucide-react';
import { useStudio } from '../StudioContext';
import { usePushConflictBanner } from '@/app/providers/PushConflictBannerProvider';
import { formatVersionSelectorLabel } from '@/app/utils/version-display';
import {
  countAuthoredRevisionsTowardHead,
  isRemoteHeadAheadOfSelection,
} from '@/app/utils/studio-sync-indicators';
import {
  branchDivergenceChipToneClasses,
  getBranchDivergenceChipPresentation,
} from '@/app/ade/studio/lib/branch-divergence-chip-copy';
import { resolveActiveBranchForRevision } from '@/app/ade/studio/lib/studio-branch-resolve';
import { Spinner } from '@/app/components/ui/Spinner';
import type { Version } from '../editor/components/types';
import type { VersionBranchRow } from '@/app/components/ade/version-dialogs/types';
import { CommitRevisionDialog } from '@/app/components/ade/version-dialogs/CommitRevisionDialog';
import { BranchFromRevisionDialog } from '@/app/components/ade/version-dialogs/BranchFromRevisionDialog';
import { VersionTagDialog } from '@/app/components/ade/version-dialogs/VersionTagDialog';
import { MergeBranchesDialog } from '@/app/components/ade/version-dialogs/MergeBranchesDialog';
import { RollbackBranchDialog } from '@/app/components/ade/version-dialogs/RollbackBranchDialog';
import { CanvasHistoryGraphDialog } from './CanvasHistoryGraphDialog';
import { BranchSwitchSubmenu } from './BranchSwitchSubmenu';
import { useStudioBranchDivergence } from '../hooks/useStudioBranchDivergence';

export type DesignerCanvasGitMenuProps = {
  versions: Version[];
  setVersions: Dispatch<SetStateAction<Version[]>>;
};

export type DesignerCanvasGitMenuHandle = {
  /** Opens the commit dialog (e.g. canvas ⌘/Ctrl+Enter). */
  openCommit: () => void;
};

function versionSyncRow(v: Version) {
  return {
    id: v.id,
    parent_version_id: (v as { parent_version_id?: string | null }).parent_version_id ?? null,
    creator_id: (v as { creator_id?: string | null }).creator_id ?? null,
  };
}

type MenuDialog =
  | null
  | 'commit'
  | 'branch'
  | 'tag'
  | 'merge'
  | 'rollback'
  | 'history';

export const DesignerCanvasGitMenu = forwardRef<DesignerCanvasGitMenuHandle, DesignerCanvasGitMenuProps>(
  function DesignerCanvasGitMenu({ versions, setVersions }, ref) {
  const { data: session } = useSession();
  const router = useRouter();
  const { conflict, clearPushConflict, setPushConflictFrom409 } = usePushConflictBanner();

  const [pullLoading, setPullLoading] = useState(false);
  const [refreshLoading, setRefreshLoading] = useState(false);
  const [openDialog, setOpenDialog] = useState<MenuDialog>(null);
  const [mergeBranchPreset, setMergeBranchPreset] = useState<{
    source: string;
    target: string;
  } | null>(null);

  const {
    showDivergence: showSyncFromMain,
    data: branchDivergenceData,
    loading: branchDivergenceLoading,
    error: branchDivergenceError,
    defaultBranchName: syncDefaultBranchName,
    activeBranchName: syncActiveBranchName,
    displayBranch,
  } = useStudioBranchDivergence();

  const {
    selectedProjectId,
    selectedVersionId,
    selectedBranchId,
    setSelectedVersionId,
    isReadOnly,
    setIsReadOnly,
    triggerCanvasRefresh,
    triggerSidebarRefresh,
    syncLocalDirty,
    canvasPresentationMode,
    setVersionBranchesForProject,
    versionBranchesByProjectId,
    registerBranchFromRevisionOpener,
    registerGitPaletteHandler,
  } = useStudio();

  const branchesForLabel = useMemo(
    () => (selectedProjectId ? (versionBranchesByProjectId[selectedProjectId] ?? []) : []),
    [selectedProjectId, versionBranchesByProjectId]
  );

  const resolvedBranch = useMemo(() => {
    if (!selectedVersionId || !branchesForLabel.length) return null;
    return resolveActiveBranchForRevision(selectedVersionId, branchesForLabel);
  }, [selectedVersionId, branchesForLabel]);

  const lockBranchId = useMemo(() => {
    if (selectedBranchId && branchesForLabel.some((b) => b.id === selectedBranchId)) {
      return selectedBranchId;
    }
    return resolvedBranch?.id ?? null;
  }, [selectedBranchId, branchesForLabel, resolvedBranch]);

  const branchLabel = displayBranch?.name?.trim() || syncActiveBranchName || '—';

  const divergenceCompact = useMemo(() => {
    if (branchDivergenceError) {
      return { label: 'Divergence unavailable', tone: 'muted' as const };
    }
    if (showSyncFromMain) {
      if (!branchDivergenceData && branchDivergenceLoading) {
        return { label: 'Checking vs default…', tone: 'muted' as const };
      }
      if (!branchDivergenceData) return null;
      const against = branchDivergenceData.against?.name?.trim() || syncDefaultBranchName || 'default';
      return getBranchDivergenceChipPresentation(
        branchDivergenceData.ahead ?? 0,
        branchDivergenceData.behind ?? 0,
        against
      );
    }
    const def = syncDefaultBranchName?.trim() || 'default';
    return getBranchDivergenceChipPresentation(0, 0, def);
  }, [
    branchDivergenceError,
    showSyncFromMain,
    branchDivergenceData,
    branchDivergenceLoading,
    syncDefaultBranchName,
  ]);

  useEffect(() => {
    registerBranchFromRevisionOpener(() => {
      setOpenDialog('branch');
    });
    return () => {
      registerBranchFromRevisionOpener(null);
    };
  }, [registerBranchFromRevisionOpener]);

  const refreshBranchList = useCallback(async () => {
    if (!selectedProjectId) return;
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(selectedProjectId)}/version-branches`);
      const d = (await r.json()) as { success?: boolean; branches?: unknown[] };
      if (r.ok && d.success && Array.isArray(d.branches)) {
        setVersionBranchesForProject(selectedProjectId, d.branches as VersionBranchRow[]);
      }
    } catch {
      /* chip / sync will refetch */
    }
  }, [selectedProjectId, setVersionBranchesForProject]);

  const sessionUserId = (session?.user as { user_id?: string } | undefined)?.user_id;
  const isTenantAdmin = Boolean((session?.user as { is_tenant_admin?: boolean } | undefined)?.is_tenant_admin);

  const serverAheadForProject =
    conflict && selectedProjectId && conflict.projectId === selectedProjectId ? conflict : null;

  const syncVersionsForMetrics = useMemo(() => versions.map(versionSyncRow), [versions]);

  const authoredRevisionCount = useMemo(
    () => countAuthoredRevisionsTowardHead(syncVersionsForMetrics, selectedVersionId ?? '', sessionUserId),
    [syncVersionsForMetrics, selectedVersionId, sessionUserId]
  );

  const serverHeadAheadOfSelection = useMemo(
    () => isRemoteHeadAheadOfSelection(syncVersionsForMetrics, selectedVersionId ?? ''),
    [syncVersionsForMetrics, selectedVersionId]
  );

  const showServerAhead = Boolean(serverAheadForProject) || serverHeadAheadOfSelection;

  const currentVersion = useMemo(
    () => versions.find((v) => String(v.id) === String(selectedVersionId)),
    [versions, selectedVersionId]
  );

  const currentRevisionRef = useMemo(
    () =>
      currentVersion
        ? {
            id: currentVersion.id,
            version_id: currentVersion.version_id,
            shortMessage: currentVersion.shortMessage ?? currentVersion.description ?? null,
          }
        : null,
    [currentVersion]
  );

  const refreshVersionList = useCallback(async (): Promise<Version[] | null> => {
    if (!selectedProjectId) return null;
    try {
      const response = await fetch(`/api/versions?projectId=${encodeURIComponent(selectedProjectId)}`);
      const result = await response.json();
      if (!response.ok || !result.success || !Array.isArray(result.versions)) {
        return null;
      }
      const list = result.versions as Version[];
      setVersions(list);
      return list;
    } catch {
      return null;
    }
  }, [selectedProjectId, setVersions]);

  const handleOpenVersionsDashboard = useCallback(() => {
    if (!selectedProjectId) return;
    router.push(`/ade/dashboard/versions?projectId=${encodeURIComponent(selectedProjectId)}`);
  }, [selectedProjectId, router]);

  const handleCompareWithParent = useCallback(() => {
    if (!selectedProjectId || !selectedVersionId) return;
    router.push(
      `/ade/dashboard/versions?projectId=${encodeURIComponent(selectedProjectId)}&compareHead=${encodeURIComponent(selectedVersionId)}`
    );
  }, [selectedProjectId, selectedVersionId, router]);

  const handleRefreshRevisionList = useCallback(async () => {
    if (!selectedProjectId) return;
    setRefreshLoading(true);
    try {
      const list = await refreshVersionList();
      if (!list) {
        toast.error('Could not refresh revisions.');
        return;
      }
      const stillExists = list.some((v) => String(v.id) === String(selectedVersionId));
      if (!stillExists && list[0]) {
        setSelectedVersionId(list[0].id);
        setIsReadOnly(list[0].published ?? false);
        toast.message('The selected revision is no longer in this project; switched to the newest one.');
      } else {
        toast.success('Revision list updated.');
      }
      triggerSidebarRefresh();
    } finally {
      setRefreshLoading(false);
    }
  }, [
    selectedProjectId,
    selectedVersionId,
    refreshVersionList,
    setSelectedVersionId,
    setIsReadOnly,
    triggerSidebarRefresh,
  ]);

  const handlePullLatest = useCallback(async () => {
    if (!selectedProjectId) return;
    setPullLoading(true);
    try {
      const list = await refreshVersionList();
      if (!list) {
        toast.error('Could not load revisions.');
        return;
      }
      const headId = serverAheadForProject?.currentHeadRevisionId;
      const fromConflict = headId ? list.find((v) => v.id === headId) : undefined;
      const next = fromConflict ?? list[0];
      if (!next) {
        toast.error('No revisions available. Check the project in Control Panel.');
        return;
      }
      setSelectedVersionId(next.id);
      setIsReadOnly(next.published ?? false);
      clearPushConflict();
      triggerCanvasRefresh();
      triggerSidebarRefresh();
      toast.success('Now on the latest revision.');
    } finally {
      setPullLoading(false);
    }
  }, [
    selectedProjectId,
    serverAheadForProject,
    refreshVersionList,
    setSelectedVersionId,
    setIsReadOnly,
    clearPushConflict,
    triggerCanvasRefresh,
    triggerSidebarRefresh,
  ]);

  const handleCheckoutRevision = useCallback(
    (revisionId: string) => {
      if (!revisionId) return;
      const next = versions.find((v) => v.id === revisionId);
      setSelectedVersionId(revisionId);
      if (next) setIsReadOnly(next.published ?? false);
      triggerCanvasRefresh();
    },
    [versions, setSelectedVersionId, setIsReadOnly, triggerCanvasRefresh]
  );

  const handleSyncFromDefaultBranch = useCallback(() => {
    const hasBranchDivergenceData = Boolean(branchDivergenceData);
    const branchBehindCount = branchDivergenceData?.behind ?? 0;
    const canSyncFromMain =
      !branchDivergenceLoading &&
      !branchDivergenceError &&
      Boolean(syncDefaultBranchName) &&
      Boolean(syncActiveBranchName) &&
      hasBranchDivergenceData &&
      branchBehindCount > 0;
    if (!canSyncFromMain) {
      toast.message(
        'Nothing to sync from the default branch right now (up to date, still loading, or status unavailable).'
      );
      return;
    }
    setMergeBranchPreset({
      source: syncDefaultBranchName!,
      target: syncActiveBranchName!,
    });
    setOpenDialog('merge');
  }, [
    branchDivergenceData,
    branchDivergenceLoading,
    branchDivergenceError,
    syncDefaultBranchName,
    syncActiveBranchName,
  ]);

  useEffect(() => {
    if (!selectedProjectId || !selectedVersionId || canvasPresentationMode) {
      registerGitPaletteHandler('branch', null);
      registerGitPaletteHandler('checkout', null);
      registerGitPaletteHandler('pull', null);
      registerGitPaletteHandler('sync', null);
      registerGitPaletteHandler('merge', null);
      registerGitPaletteHandler('rollback', null);
      return;
    }
    registerGitPaletteHandler('branch', () => setOpenDialog('branch'));
    registerGitPaletteHandler('checkout', () => setOpenDialog('history'));
    registerGitPaletteHandler('pull', () => {
      void handlePullLatest();
    });
    registerGitPaletteHandler('sync', handleSyncFromDefaultBranch);
    registerGitPaletteHandler('merge', () => {
      setMergeBranchPreset(null);
      setOpenDialog('merge');
    });
    registerGitPaletteHandler('rollback', () => setOpenDialog('rollback'));
    return () => {
      registerGitPaletteHandler('branch', null);
      registerGitPaletteHandler('checkout', null);
      registerGitPaletteHandler('pull', null);
      registerGitPaletteHandler('sync', null);
      registerGitPaletteHandler('merge', null);
      registerGitPaletteHandler('rollback', null);
    };
  }, [
    selectedProjectId,
    selectedVersionId,
    canvasPresentationMode,
    registerGitPaletteHandler,
    handlePullLatest,
    handleSyncFromDefaultBranch,
  ]);

  const tryOpenCommit = useCallback(() => {
    if (!selectedProjectId || !selectedVersionId) return;
    if (isReadOnly) {
      toast.warning('This revision is read-only. Pull the latest to commit new work.');
      return;
    }
    setOpenDialog('commit');
  }, [selectedProjectId, selectedVersionId, isReadOnly]);

  useImperativeHandle(ref, () => ({ openCommit: tryOpenCommit }), [tryOpenCommit]);

  useEffect(() => {
    if (!selectedProjectId || !selectedVersionId || canvasPresentationMode) {
      registerGitPaletteHandler('commit', null);
      return;
    }
    registerGitPaletteHandler('commit', tryOpenCommit);
    return () => {
      registerGitPaletteHandler('commit', null);
    };
  }, [selectedProjectId, selectedVersionId, canvasPresentationMode, tryOpenCommit, registerGitPaletteHandler]);

  if (!selectedProjectId || !selectedVersionId || canvasPresentationMode) {
    return null;
  }

  const pullDisabled = !showServerAhead || pullLoading;
  const canCommit = !isReadOnly;
  const hasCurrent = Boolean(currentRevisionRef?.id);

  /** Floating glass chip — matches Layout / Export (translucent, not a solid group panel). */
  const toolbarIconButtonClass =
    'shrink-0 p-2 text-sm font-medium rounded-lg border border-gray-200/55 dark:border-gray-600/45 bg-white/45 dark:bg-gray-900/40 text-gray-800 dark:text-gray-200 backdrop-blur-md transition-all duration-200 shadow-md hover:shadow-lg hover:bg-white/65 dark:hover:bg-gray-900/55 hover:border-indigo-300/60 dark:hover:border-indigo-500/45 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/30 data-[state=open]:border-indigo-400/70 dark:data-[state=open]:border-indigo-500/50 data-[state=open]:bg-indigo-50/55 dark:data-[state=open]:bg-indigo-950/35 data-[state=open]:shadow-lg';

  const itemClass =
    'flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-gray-800 outline-none data-[highlighted]:bg-gray-100 data-[disabled]:opacity-50 data-[disabled]:cursor-not-allowed dark:text-gray-200 dark:data-[highlighted]:bg-gray-700';

  const sectionLabelClass =
    'px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400';

  return (
    <>
      <DropdownMenu.Root modal={false}>
        <DropdownMenu.Trigger asChild>
          <button
            type="button"
            className={toolbarIconButtonClass}
            title="Revision and sync — commit, branch, tag, merge, history"
            aria-label="Revision and sync"
          >
            <GitBranch className="h-5 w-5" aria-hidden />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            className="z-[10050] min-w-[280px] overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg dark:border-gray-600 dark:bg-gray-800"
            sideOffset={6}
            align="end"
          >
            <div className="border-b border-gray-100 px-3 py-2 dark:border-gray-700">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                Branch
              </div>
              <div className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">{branchLabel}</div>
              {divergenceCompact ? (
                <p className={`mt-0.5 text-xs ${branchDivergenceChipToneClasses(divergenceCompact.tone)}`}>
                  {divergenceCompact.label}
                </p>
              ) : null}

              <div className="mt-2 text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                Revision
              </div>
              <div className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                {currentVersion ? formatVersionSelectorLabel(currentVersion) : '—'}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-gray-600 dark:text-gray-400">
                {currentVersion?.published ? (
                  <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200">
                    Published
                  </span>
                ) : (
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-700 dark:bg-slate-300/10 dark:text-slate-300">
                    Draft
                  </span>
                )}
                {authoredRevisionCount > 0 && (
                  <span title="Revisions you authored between this selection and the latest revision (main lineage).">
                    {authoredRevisionCount} yours → head
                  </span>
                )}
                {syncLocalDirty && <span className="text-amber-700 dark:text-amber-300">Unsaved layout</span>}
                {showServerAhead && (
                  <span className="text-indigo-700 dark:text-indigo-300">Newer on server</span>
                )}
              </div>

              <DropdownMenu.Sub>
                <DropdownMenu.SubTrigger
                  className={`${itemClass} mt-2 -mx-1 flex w-[calc(100%+0.5rem)] cursor-pointer items-center rounded-md border border-gray-100 dark:border-gray-700`}
                >
                  <GitBranch className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
                  <span className="flex-1 text-left">Switch branch</span>
                  <ChevronRight className="h-4 w-4 shrink-0 opacity-50" aria-hidden />
                </DropdownMenu.SubTrigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.SubContent
                    className="z-[10055] max-h-[min(60vh,20rem)] min-w-[220px] overflow-y-auto rounded-lg border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-600 dark:bg-gray-800"
                    sideOffset={6}
                    alignOffset={-2}
                  >
                    <BranchSwitchSubmenu versions={versions} setVersions={setVersions} itemClass={itemClass} />
                  </DropdownMenu.SubContent>
                </DropdownMenu.Portal>
              </DropdownMenu.Sub>
            </div>

            <div className={sectionLabelClass}>This revision</div>
            <DropdownMenu.Item
              className={itemClass}
              disabled={!canCommit || !selectedProjectId}
              onSelect={(e) => {
                e.preventDefault();
                if (!canCommit) {
                  toast.warning('This revision is read-only. Pull the latest to commit new work.');
                  return;
                }
                setOpenDialog('commit');
              }}
            >
              <GitCommit className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
              <span className="flex-1">Commit new revision…</span>
            </DropdownMenu.Item>

            <DropdownMenu.Item
              className={itemClass}
              disabled={!hasCurrent}
              onSelect={(e) => {
                e.preventDefault();
                setOpenDialog('tag');
              }}
            >
              <Tag className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
              <span className="flex-1">Tag this revision…</span>
            </DropdownMenu.Item>

            <DropdownMenu.Item
              className={itemClass}
              disabled={!hasCurrent}
              onSelect={(e) => {
                e.preventDefault();
                handleCompareWithParent();
              }}
            >
              <GitCompareArrows className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
              <span className="flex-1">Compare with parent…</span>
              <ExternalLink className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden />
            </DropdownMenu.Item>

            <DropdownMenu.Separator className="my-1 h-px bg-gray-100 dark:bg-gray-700" />
            <div className={sectionLabelClass}>Branching</div>

            <DropdownMenu.Item
              className={itemClass}
              onSelect={(e) => {
                e.preventDefault();
                setMergeBranchPreset(null);
                setOpenDialog('merge');
              }}
            >
              <GitMerge className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
              <span className="flex-1">Merge branches…</span>
            </DropdownMenu.Item>

            <DropdownMenu.Item
              className={itemClass}
              disabled={!hasCurrent}
              onSelect={(e) => {
                e.preventDefault();
                setOpenDialog('rollback');
              }}
            >
              <Undo2 className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
              <span className="flex-1">Rollback to this revision…</span>
            </DropdownMenu.Item>

            <DropdownMenu.Separator className="my-1 h-px bg-gray-100 dark:bg-gray-700" />
            <div className={sectionLabelClass}>History and sync</div>

            <DropdownMenu.Item
              className={itemClass}
              onSelect={(e) => {
                e.preventDefault();
                setOpenDialog('history');
              }}
            >
              <FileSearch className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
              <span className="flex-1">Show history graph…</span>
            </DropdownMenu.Item>

            {showSyncFromMain
              ? (() => {
                  const hasBranchDivergenceData = Boolean(branchDivergenceData);
                  const branchBehindCount = branchDivergenceData?.behind ?? 0;
                  const canSyncFromMain =
                    !branchDivergenceLoading &&
                    !branchDivergenceError &&
                    Boolean(syncDefaultBranchName) &&
                    Boolean(syncActiveBranchName) &&
                    hasBranchDivergenceData &&
                    branchBehindCount > 0;
                  const defaultBranchLabel = syncDefaultBranchName || 'default branch';

                  return (
                    <DropdownMenu.Item
                      className={itemClass}
                      title={
                        branchDivergenceError
                          ? branchDivergenceError
                          : hasBranchDivergenceData && branchBehindCount === 0 && !branchDivergenceLoading
                            ? `Up to date with ${defaultBranchLabel}.`
                            : undefined
                      }
                      disabled={!canSyncFromMain}
                      onSelect={(e) => {
                        e.preventDefault();
                        handleSyncFromDefaultBranch();
                      }}
                    >
                      {branchDivergenceLoading && !hasBranchDivergenceData ? (
                        <Spinner size="sm" className="shrink-0" aria-hidden />
                      ) : (
                        <ArrowDownToLine className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
                      )}
                      <span className="flex-1">
                        {branchDivergenceError
                          ? `Sync from ${defaultBranchLabel} — status unavailable`
                          : !hasBranchDivergenceData
                            ? `Sync from ${defaultBranchLabel}…`
                            : branchBehindCount > 0
                              ? `Sync from ${defaultBranchLabel} (${branchBehindCount} behind)`
                              : `Sync from ${defaultBranchLabel} — up to date`}
                      </span>
                    </DropdownMenu.Item>
                  );
                })()
              : null}

            <DropdownMenu.Item
              className={itemClass}
              onSelect={(e) => {
                e.preventDefault();
                void handlePullLatest();
              }}
              disabled={pullDisabled}
            >
              {pullLoading ? (
                <Spinner size="sm" className="shrink-0" aria-hidden />
              ) : (
                <Download className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
              )}
              <span className="flex-1">Switch to latest revision (pull)</span>
            </DropdownMenu.Item>

            <DropdownMenu.Item
              className={itemClass}
              onSelect={(e) => {
                e.preventDefault();
                void handleRefreshRevisionList();
              }}
              disabled={refreshLoading}
            >
              {refreshLoading ? (
                <Spinner size="sm" className="shrink-0" aria-hidden />
              ) : (
                <RefreshCw className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
              )}
              <span className="flex-1">Refresh revision list</span>
            </DropdownMenu.Item>

            <DropdownMenu.Item
              className={itemClass}
              onSelect={(e) => {
                e.preventDefault();
                handleOpenVersionsDashboard();
              }}
            >
              <History className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
              <span className="flex-1">Open Versions dashboard</span>
              <ExternalLink className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden />
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>

      {selectedProjectId && (
        <>
          <CommitRevisionDialog
            open={openDialog === 'commit'}
            onOpenChange={(o) => setOpenDialog(o ? 'commit' : null)}
            projectId={selectedProjectId}
            currentRevision={currentRevisionRef}
            lockedBranchId={lockBranchId}
            studioSelectedBranchId={selectedBranchId}
            onStaleHead={(info) => {
              if (!selectedProjectId) return;
              setPushConflictFrom409({
                projectId: selectedProjectId,
                message: info.message ?? 'Server has a newer head revision.',
                currentHeadRevisionId: info.currentHeadRevisionId,
                currentHead: info.currentHead ?? null,
              });
            }}
            onCreated={async (result) => {
              const list = await refreshVersionList();
              await refreshBranchList();
              if (result.id) {
                setSelectedVersionId(result.id);
                setIsReadOnly(result.published ?? false);
              } else if (list && list[0]) {
                setSelectedVersionId(list[0].id);
                setIsReadOnly(list[0].published ?? false);
              }
              triggerCanvasRefresh();
              triggerSidebarRefresh();
            }}
          />

          <BranchFromRevisionDialog
            open={openDialog === 'branch'}
            onOpenChange={(o) => setOpenDialog(o ? 'branch' : null)}
            projectId={selectedProjectId}
            revision={currentRevisionRef}
            onCreated={() => {
              triggerSidebarRefresh();
            }}
          />

          <VersionTagDialog
            open={openDialog === 'tag'}
            onOpenChange={(o) => setOpenDialog(o ? 'tag' : null)}
            projectId={selectedProjectId}
            revision={currentRevisionRef}
            isTenantAdmin={isTenantAdmin}
            onCreated={() => {
              triggerSidebarRefresh();
            }}
          />

          <MergeBranchesDialog
            open={openDialog === 'merge'}
            onOpenChange={(o) => {
              if (!o) setMergeBranchPreset(null);
              setOpenDialog(o ? 'merge' : null);
            }}
            projectId={selectedProjectId}
            isTenantAdmin={isTenantAdmin}
            initialSourceBranch={mergeBranchPreset?.source}
            initialTargetBranch={mergeBranchPreset?.target}
            onMerged={async (result) => {
              const list = await refreshVersionList();
              await refreshBranchList();
              if (result.version?.id && list?.some((v) => v.id === result.version?.id)) {
                setSelectedVersionId(result.version.id);
                const next = list.find((v) => v.id === result.version?.id);
                if (next) setIsReadOnly(next.published ?? false);
              } else if (list?.[0]) {
                setSelectedVersionId(list[0].id);
                setIsReadOnly(list[0].published ?? false);
              }
              clearPushConflict();
              triggerCanvasRefresh();
              triggerSidebarRefresh();
            }}
          />

          <RollbackBranchDialog
            open={openDialog === 'rollback'}
            onOpenChange={(o) => setOpenDialog(o ? 'rollback' : null)}
            projectId={selectedProjectId}
            targetRevision={currentRevisionRef}
            onRolledBack={async (result) => {
              const list = await refreshVersionList();
              if (result.version?.id && list?.some((v) => v.id === result.version?.id)) {
                setSelectedVersionId(result.version.id);
                const next = list.find((v) => v.id === result.version?.id);
                if (next) setIsReadOnly(next.published ?? false);
              } else if (list?.[0]) {
                setSelectedVersionId(list[0].id);
                setIsReadOnly(list[0].published ?? false);
              }
              triggerCanvasRefresh();
              triggerSidebarRefresh();
            }}
          />

          <CanvasHistoryGraphDialog
            open={openDialog === 'history'}
            onOpenChange={(o) => setOpenDialog(o ? 'history' : null)}
            projectId={selectedProjectId}
            versions={versions}
            headRevisionId={currentRevisionRef?.id ?? null}
            onCheckoutRevision={(id) => {
              handleCheckoutRevision(id);
              setOpenDialog(null);
            }}
            onBranchFromRevision={(id) => {
              const target = versions.find((v) => v.id === id);
              if (!target) return;
              setSelectedVersionId(id);
              if (target) setIsReadOnly(target.published ?? false);
              setOpenDialog('branch');
            }}
          />
        </>
      )}
    </>
  );
});

DesignerCanvasGitMenu.displayName = 'DesignerCanvasGitMenu';
