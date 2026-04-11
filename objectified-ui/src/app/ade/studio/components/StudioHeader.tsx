'use client';

import * as React from 'react';
import { useSession } from 'next-auth/react';
import { useRouter, usePathname } from 'next/navigation';
import { toast } from 'sonner';
import { Check, Gauge, Settings, X } from 'lucide-react';
import * as Select from '@radix-ui/react-select';
import * as Dialog from '@radix-ui/react-dialog';
import * as ToggleGroup from '@radix-ui/react-toggle-group';
import { useStudio } from '../StudioContext';
import { Spinner } from '../../../components/ui/Spinner';
import {
  getTagsForProject
} from '../../../../../lib/db/helper';
import CanvasSettingsDialog from './CanvasSettingsDialog';
import { cn } from '../../../../../lib/utils';
import { getNumericScoreTier, NUMERIC_SCORE_TIER_LEGEND } from '@/app/utils/numeric-score-tier';
import { OVERALL_SCHEMA_QUALITY_WEIGHTS } from '@/app/utils/overall-schema-quality';
import RevisionDeprecationBanner from '@/app/components/ade/RevisionDeprecationBanner';
import ServerAheadPushBanner from '@/app/components/ade/ServerAheadPushBanner';
import { usePushConflictBanner } from '@/app/providers/PushConflictBannerProvider';
import { isRevisionDeprecated } from '@/app/utils/revision-deprecation';

interface Project {
  id: string;
  name: string;
  slug: string;
}

interface Version {
  id: string;
  version_id: string;
  description: string;
  published: boolean;
  metadata?: Record<string, unknown>;
}

type ViewMode = 'editor' | 'paths' | 'code';

interface StudioHeaderProps {
  projectTags?: any[];
  onProjectTagsLoaded?: (tags: any[]) => void;
}

export default function StudioHeader({ onProjectTagsLoaded }: StudioHeaderProps) {
  const { data: session } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const currentTenantId = (session?.user as any)?.current_tenant_id;

  const {
    selectedProjectId,
    setSelectedProjectId: setContextProjectId,
    selectedVersionId,
    setSelectedVersionId: setContextVersionId,
    setIsReadOnly,
    clickToFocusEnabled,
    setClickToFocusEnabled,
    gridSize,
    setGridSize,
    snapToGrid,
    setSnapToGrid,
    gridStyle,
    setGridStyle,
    showGrid,
    setShowGrid,
    canvasBackground,
    setCanvasBackground,
    smartGuidesEnabled,
    setSmartGuidesEnabled,
    edgeStyling,
    setEdgeStyling,
    edgeRouting,
    setEdgeRouting,
    edgeAnimation,
    setEdgeAnimation,
    searchHistoryCount,
    clearSearchHistoryFn,
    clearCanvasSelectionFn,
    schemaQualityScore,
    schemaQualityDetail,
    triggerCanvasRefresh,
    triggerSidebarRefresh,
  } = useStudio();

  const { conflict, clearPushConflict } = usePushConflictBanner();
  const [pullReconcileLoading, setPullReconcileLoading] = React.useState(false);

  const [schemaQualityDialogOpen, setSchemaQualityDialogOpen] = React.useState(false);

  const [projects, setProjects] = React.useState<Project[]>([]);
  const [versions, setVersions] = React.useState<Version[]>([]);
  const [localProjectId, setLocalProjectId] = React.useState<string>(selectedProjectId || '');
  const [localVersionId, setLocalVersionId] = React.useState<string>(selectedVersionId || '');
  const [isLoadingProjects, setIsLoadingProjects] = React.useState(false);
  const [isLoadingVersions, setIsLoadingVersions] = React.useState(false);
  const [settingsDialogOpen, setSettingsDialogOpen] = React.useState(false);

  // Determine current view mode from pathname
  const viewMode: ViewMode = pathname?.includes('/code')
    ? 'code'
    : pathname?.includes('/paths')
      ? 'paths'
      : 'editor';

  // Handle settings save
  const handleSettingsSave = React.useCallback((settings: {
    clickToFocusEnabled: boolean;
    snapToGrid: boolean;
    smartGuidesEnabled: boolean;
    showGrid: boolean;
    gridSize: number;
    gridStyle: 'dots' | 'lines' | 'cross';
    canvasBackground: typeof canvasBackground;
    edgeStyling: typeof edgeStyling;
    edgeRouting: typeof edgeRouting;
    edgeAnimation: typeof edgeAnimation;
  }) => {
    setClickToFocusEnabled(settings.clickToFocusEnabled);
    localStorage.setItem('clickToFocusEnabled', JSON.stringify(settings.clickToFocusEnabled));

    setSnapToGrid(settings.snapToGrid);
    localStorage.setItem('snapToGrid', JSON.stringify(settings.snapToGrid));

    setSmartGuidesEnabled(settings.smartGuidesEnabled);
    localStorage.setItem('smartGuidesEnabled', JSON.stringify(settings.smartGuidesEnabled));

    setShowGrid(settings.showGrid);
    localStorage.setItem('showGrid', JSON.stringify(settings.showGrid));

    setGridSize(settings.gridSize);
    localStorage.setItem('gridSize', String(settings.gridSize));

    setGridStyle(settings.gridStyle);
    localStorage.setItem('gridStyle', settings.gridStyle);

    setCanvasBackground(settings.canvasBackground);
    localStorage.setItem('canvasBackground', JSON.stringify(settings.canvasBackground));

    setEdgeStyling(settings.edgeStyling);
    localStorage.setItem('edgeStyling', JSON.stringify(settings.edgeStyling));

    setEdgeRouting(settings.edgeRouting);
    localStorage.setItem('edgeRouting', settings.edgeRouting);

    setEdgeAnimation(settings.edgeAnimation);
    localStorage.setItem('edgeAnimation', settings.edgeAnimation);
  }, [setClickToFocusEnabled, setSnapToGrid, setSmartGuidesEnabled, setShowGrid, setGridSize, setGridStyle, setCanvasBackground, setEdgeStyling, setEdgeRouting, setEdgeAnimation]);

  // Sync local state with context
  React.useEffect(() => {
    if (selectedProjectId !== localProjectId) {
      setLocalProjectId(selectedProjectId || '');
    }
    if (selectedVersionId !== localVersionId) {
      setLocalVersionId(selectedVersionId || '');
    }
  }, [selectedProjectId, selectedVersionId]);

  // Load projects on mount
  React.useEffect(() => {
    const loadProjects = async () => {
      if (!currentTenantId) {
        setProjects([]);
        return;
      }
      setIsLoadingProjects(true);
      try {
        const response = await fetch('/api/projects');
        if (!response.ok) {
          throw new Error(`Failed to fetch projects: ${response.statusText}`);
        }
        const data = await response.json();
        if (data.success && data.projects) {
          setProjects(data.projects);
        } else {
          throw new Error(data.error || 'Failed to load projects');
        }
      } catch (error) {
        console.error('Failed to load projects:', error);
        setProjects([]);
      } finally {
        setIsLoadingProjects(false);
      }
    };
    loadProjects();
  }, [currentTenantId]);

  // Load versions when project changes and auto-select most recent
  React.useEffect(() => {
    const loadVersions = async () => {
      if (!localProjectId) {
        setVersions([]);
        return;
      }
      setIsLoadingVersions(true);
      try {
        const response = await fetch(`/api/versions?projectId=${localProjectId}`);
        if (!response.ok) {
          throw new Error(`Failed to fetch versions: ${response.statusText}`);
        }
        const result = await response.json();
        if (result.success && result.versions) {
          setVersions(result.versions);

          // Auto-select the most recent version (first in the list)
          if (result.versions.length > 0) {
            const mostRecentVersion = result.versions[0];
            setLocalVersionId(mostRecentVersion.id);
            setContextVersionId(mostRecentVersion.id);
            setIsReadOnly(mostRecentVersion.published ?? false);
          }
        } else {
          throw new Error(result.error || 'Failed to load versions');
        }
      } catch (error) {
        console.error('Failed to load versions:', error);
        setVersions([]);
      } finally {
        setIsLoadingVersions(false);
      }
    };
    loadVersions();
  }, [localProjectId, setContextVersionId, setIsReadOnly]);

  // Load project tags when project changes
  const loadProjectTags = React.useCallback(async (projectId: string) => {
    if (!projectId) return;
    try {
      const result = await getTagsForProject(projectId);
      const tags = JSON.parse(result);
      onProjectTagsLoaded?.(tags);
    } catch (error) {
      console.error('Failed to load project tags:', error);
    }
  }, [onProjectTagsLoaded]);

  // Handle project selection
  const handleProjectChange = (value: string) => {
    setLocalProjectId(value);
    setContextProjectId(value);
    setLocalVersionId('');
    setContextVersionId('');
    setIsReadOnly(false);
    if (value) {
      loadProjectTags(value);
    }
  };

  // Handle version selection
  const handleVersionChange = (value: string) => {
    setLocalVersionId(value);
    setContextVersionId(value);
    const version = versions.find(v => v.id === value);
    setIsReadOnly(version?.published ?? false);
  };

  const serverAheadForProject =
    conflict && localProjectId && conflict.projectId === localProjectId ? conflict : null;

  const handlePullReconcile = React.useCallback(async () => {
    if (!localProjectId || !serverAheadForProject) return;
    setPullReconcileLoading(true);
    try {
      const response = await fetch(`/api/versions?projectId=${encodeURIComponent(localProjectId)}`);
      const result = await response.json();
      if (!response.ok || !result.success || !Array.isArray(result.versions)) {
        toast.error(typeof result.error === 'string' ? result.error : 'Could not refresh versions.');
        return;
      }
      const list = result.versions as Version[];
      setVersions(list);
      const headId = serverAheadForProject.currentHeadRevisionId;
      const match = headId ? list.find((v) => v.id === headId) : undefined;
      const next = match ?? list[0];
      if (next) {
        setLocalVersionId(next.id);
        setContextVersionId(next.id);
        setIsReadOnly(next.published ?? false);
      }
      clearPushConflict();
      triggerCanvasRefresh();
      triggerSidebarRefresh();
      toast.success('Now on the latest revision.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Pull failed');
    } finally {
      setPullReconcileLoading(false);
    }
  }, [
    localProjectId,
    serverAheadForProject,
    setContextVersionId,
    setIsReadOnly,
    clearPushConflict,
    triggerCanvasRefresh,
    triggerSidebarRefresh,
  ]);

  const handleOpenMergeFromBanner = React.useCallback(() => {
    const pid = serverAheadForProject?.projectId ?? localProjectId;
    if (!pid) return;
    router.push(`/ade/dashboard/versions?merge=1&projectId=${encodeURIComponent(pid)}`);
  }, [serverAheadForProject?.projectId, localProjectId, router]);

  // Handle view mode change
  const handleViewModeChange = (value: string) => {
    if (!value) return;
    if (value === 'editor') {
      router.push('/ade/studio/editor');
    } else if (value === 'paths') {
      router.push('/ade/studio/paths');
    } else if (value === 'code') {
      clearCanvasSelectionFn?.();
      router.push('/ade/studio/code');
    }
  };

  if (!currentTenantId) {
    return null;
  }

  return (
    <div className="bg-gradient-to-r from-white via-slate-50 to-white dark:from-gray-800 dark:via-gray-800 dark:to-gray-800 border-b border-gray-200/80 dark:border-gray-700/80 px-2 py-1.5 shadow-sm" style={{ position: 'fixed', top: 48, left: 0, right: 0, zIndex: 1000 }}>
      <div className="flex flex-wrap items-center gap-4 w-full">
        {/* Project Selector */}
        <div className="flex items-center gap-2" style={{ position: 'relative', zIndex: 1001 }}>
          <Select.Root
            value={localProjectId}
            onValueChange={handleProjectChange}
            disabled={isLoadingProjects || !currentTenantId}
          >
            <Select.Trigger
              aria-busy={isLoadingProjects}
              className="inline-flex items-center gap-2 bg-white dark:bg-gray-700/50 rounded-lg border border-gray-200 dark:border-gray-600 shadow-sm px-3 py-2 text-sm text-gray-900 dark:text-white hover:border-indigo-300 dark:hover:border-indigo-500/50 hover:shadow-md transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/20 min-w-[220px] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoadingProjects ? (
                <Spinner size="sm" className="shrink-0" aria-hidden />
              ) : (
                <svg className="w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
              )}
              <Select.Value placeholder={isLoadingProjects ? 'Loading projects…' : 'Select project...'} />
              <Select.Icon className="ml-auto">
                <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </Select.Icon>
            </Select.Trigger>
            <Select.Portal>
              <Select.Content className="overflow-hidden bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-[9999]" position="popper" sideOffset={5}>
                <Select.Viewport className="p-1">
                  {projects.length === 0 ? (
                    <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">No projects available</div>
                  ) : (
                    projects.map((project) => (
                      <Select.Item
                        key={project.id}
                        value={project.id}
                        className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700 data-[state=checked]:bg-indigo-50 dark:data-[state=checked]:bg-indigo-900/30"
                      >
                        <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                          <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                        </Select.ItemIndicator>
                        <Select.ItemText>{project.name}</Select.ItemText>
                      </Select.Item>
                    ))
                  )}
                </Select.Viewport>
              </Select.Content>
            </Select.Portal>
          </Select.Root>
        </div>

        {/* Version Selector */}
        <div className="flex items-center gap-2" style={{ position: 'relative', zIndex: 1001 }}>
          <Select.Root
            value={localVersionId}
            onValueChange={handleVersionChange}
            disabled={isLoadingVersions || !localProjectId || versions.length === 0}
          >
            <Select.Trigger
              aria-busy={isLoadingVersions}
              className="inline-flex items-center gap-2 bg-white dark:bg-gray-700/50 rounded-lg border border-gray-200 dark:border-gray-600 shadow-sm px-3 py-2 text-sm text-gray-900 dark:text-white hover:border-indigo-300 dark:hover:border-indigo-500/50 hover:shadow-md transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/20 min-w-[220px] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoadingVersions ? (
                <Spinner size="sm" className="shrink-0" aria-hidden />
              ) : (
                <svg className="w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                </svg>
              )}
              <Select.Value placeholder={isLoadingVersions ? 'Loading versions…' : 'Select version...'} />
              <Select.Icon className="ml-auto">
                <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </Select.Icon>
            </Select.Trigger>
            <Select.Portal>
              <Select.Content className="overflow-hidden bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-[9999]" position="popper" sideOffset={5}>
                <Select.Viewport className="p-1">
                  {versions.length === 0 ? (
                    <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">No versions available</div>
                  ) : (
                    versions.map((version) => (
                      <Select.Item
                        key={version.id}
                        value={version.id}
                        className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700 data-[state=checked]:bg-indigo-50 dark:data-[state=checked]:bg-indigo-900/30"
                      >
                        <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                          <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                        </Select.ItemIndicator>
                        <Select.ItemText>
                          {version.published ? '🔒 ' : ''}{version.version_id} - {version.description}
                        </Select.ItemText>
                      </Select.Item>
                    ))
                  )}
                </Select.Viewport>
              </Select.Content>
            </Select.Portal>
          </Select.Root>
        </div>

        {/* Overall schema quality (#245) — live from Canvas; click for breakdown (#2548) */}
        {localProjectId && localVersionId && (
          <>
            {schemaQualityScore != null ? (
              <button
                type="button"
                onClick={() => setSchemaQualityDialogOpen(true)}
                className="flex items-center gap-2 rounded-xl border border-gray-200 dark:border-gray-600 bg-white/90 dark:bg-gray-700/40 px-3 py-1 shadow-sm shrink-0 text-left hover:bg-gray-50 dark:hover:bg-gray-600/50 hover:border-indigo-300 dark:hover:border-indigo-500/40 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-gray-900 transition-colors"
                title="Overall schema quality (0–100). Click for weighted breakdown and letter grade."
                aria-label="Schema quality details"
              >
                <Gauge className="w-5 h-5 text-indigo-500 shrink-0" aria-hidden />
                <div className="flex flex-col min-w-0">
                  <span className="text-[10px] uppercase tracking-wide text-gray-500 dark:text-gray-400 leading-none">
                    Schema quality
                  </span>
                  <span className="flex items-baseline gap-1.5">
                    <span
                      className={cn(
                        'text-2xl font-bold tabular-nums leading-none',
                        getNumericScoreTier(schemaQualityScore).textClass
                      )}
                    >
                      {schemaQualityScore}
                    </span>
                    {schemaQualityDetail && (
                      <span
                        className={cn(
                          'text-lg font-bold tabular-nums leading-none',
                          schemaQualityDetail.tier.textClass
                        )}
                        title={`Letter grade (${schemaQualityDetail.tier.rangeLabel})`}
                      >
                        {schemaQualityDetail.letterGrade}
                      </span>
                    )}
                  </span>
                </div>
              </button>
            ) : (
              <div
                className="flex items-center gap-2 rounded-xl border border-gray-200 dark:border-gray-600 bg-white/90 dark:bg-gray-700/40 px-3 py-1 shadow-sm shrink-0"
                title="Open the Canvas view with classes on the canvas to compute a live schema quality score."
              >
                <Gauge className="w-5 h-5 text-indigo-500 shrink-0" aria-hidden />
                <div className="flex flex-col min-w-0">
                  <span className="text-[10px] uppercase tracking-wide text-gray-500 dark:text-gray-400 leading-none">
                    Schema quality
                  </span>
                  <span className="text-2xl font-bold tabular-nums leading-none text-gray-400 dark:text-gray-500">
                    —
                  </span>
                </div>
              </div>
            )}

            <Dialog.Root open={schemaQualityDialogOpen} onOpenChange={setSchemaQualityDialogOpen}>
              <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[10000]" />
                <Dialog.Content
                  className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white dark:bg-gray-800 rounded-xl shadow-2xl z-[10001] w-full max-w-md max-h-[85vh] overflow-y-auto p-6 border border-gray-200 dark:border-gray-700"
                >
                  <div className="flex items-start justify-between gap-3 mb-4">
                    <div>
                      <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                        Schema quality
                      </Dialog.Title>
                      <Dialog.Description className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                        Weighted blend of documentation, naming, inverted structural complexity, and canvas layout. Updates live on the Canvas.
                      </Dialog.Description>
                    </div>
                    <Dialog.Close asChild>
                      <button
                        type="button"
                        className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500"
                        aria-label="Close"
                      >
                        <X className="w-5 h-5" />
                      </button>
                    </Dialog.Close>
                  </div>

                  {schemaQualityDetail ? (
                    <>
                      <div className="flex items-center justify-between gap-4 p-4 rounded-lg border border-gray-200 dark:border-gray-700 bg-gradient-to-br from-gray-50 to-gray-100 dark:from-gray-900/50 dark:to-gray-800/50 mb-4">
                        <div className="flex items-center gap-3">
                          <span
                            className={cn('text-5xl font-bold tabular-nums', schemaQualityDetail.tier.textClass)}
                            title={`${schemaQualityDetail.tier.shortLabel} (${schemaQualityDetail.tier.rangeLabel})`}
                          >
                            {schemaQualityDetail.letterGrade}
                          </span>
                          <div>
                            <div className={cn('text-base font-semibold', schemaQualityDetail.tier.textClass)}>
                              {schemaQualityDetail.tier.shortLabel} — {schemaQualityDetail.tier.detailLabel}
                            </div>
                            <div className="text-xs text-gray-500 dark:text-gray-400">
                              Letter grade · {schemaQualityDetail.tier.rangeLabel}
                            </div>
                          </div>
                        </div>
                        <div className="text-right">
                          <div className={cn('text-3xl font-bold tabular-nums', schemaQualityDetail.tier.textClass)}>
                            {schemaQualityDetail.overall}
                          </div>
                          <div className="text-xs text-gray-500 dark:text-gray-400">/ 100</div>
                        </div>
                      </div>

                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                        Default weights: documentation {OVERALL_SCHEMA_QUALITY_WEIGHTS.documentation}, naming {OVERALL_SCHEMA_QUALITY_WEIGHTS.naming}, structural load {OVERALL_SCHEMA_QUALITY_WEIGHTS.structuralLoad}
                        {schemaQualityDetail.layoutIncluded
                          ? `, canvas layout ${OVERALL_SCHEMA_QUALITY_WEIGHTS.layout}.`
                          : ' (canvas layout is included when the graph is laid out on the Canvas).'}
                      </p>

                      <div className="text-xs font-semibold text-gray-700 dark:text-gray-200 mb-2">Contributions</div>
                      <table className="w-full text-xs text-left border-collapse mb-4">
                        <thead>
                          <tr className="border-b border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400">
                            <th className="py-1.5 pr-2 font-medium">Factor</th>
                            <th className="py-1.5 pr-2 font-medium text-right tabular-nums">Value</th>
                            <th className="py-1.5 pr-2 font-medium text-right">Weight</th>
                            <th className="py-1.5 font-medium text-right tabular-nums">Pts</th>
                          </tr>
                        </thead>
                        <tbody>
                          {schemaQualityDetail.rows.map((row) => (
                            <tr key={row.id} className="border-b border-gray-100 dark:border-gray-700/80">
                              <td className="py-1.5 pr-2 text-gray-800 dark:text-gray-200">{row.label}</td>
                              <td className="py-1.5 pr-2 text-right tabular-nums text-gray-700 dark:text-gray-300">{Math.round(row.value)}</td>
                              <td className="py-1.5 pr-2 text-right tabular-nums text-gray-500 dark:text-gray-400">
                                {(row.effectiveWeight * 100).toFixed(0)}%
                              </td>
                              <td className="py-1.5 text-right tabular-nums font-medium text-gray-800 dark:text-gray-100">
                                {row.contribution.toFixed(1)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
                        Final score is the sum of contributions, rounded to a whole number 0–100 (same rule as the OpenAPI import quality score bands).
                      </p>

                      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50/80 dark:bg-gray-900/40 px-3 py-2">
                        <div className="text-[10px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">
                          Score guide
                        </div>
                        <ul className="space-y-1.5 text-xs text-gray-700 dark:text-gray-300">
                          {NUMERIC_SCORE_TIER_LEGEND.map((row) => (
                            <li key={row.band} className="flex items-start gap-2">
                              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${row.barSolidClass}`} aria-hidden />
                              <span>
                                <span className="font-medium tabular-nums">{row.rangeLabel}:</span> {row.shortLabel} — {row.detailLabel}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </>
                  ) : (
                    <p className="text-sm text-gray-600 dark:text-gray-400">
                      Detailed breakdown is unavailable. Open the Canvas with at least one class and a computed layout to see documentation, naming, structural load, and layout weights.
                    </p>
                  )}
                </Dialog.Content>
              </Dialog.Portal>
            </Dialog.Root>
          </>
        )}

        {/* View Switcher and Settings - only show when project and version selected */}
        {localProjectId && localVersionId && (
          <>
            {/* Separator */}
            <div className="h-6 w-px bg-gray-200 dark:bg-gray-600" />

            <ToggleGroup.Root
              type="single"
              value={viewMode}
              onValueChange={handleViewModeChange}
              className="inline-flex bg-gray-100 dark:bg-gray-700/50 rounded-lg p-1 shadow-inner"
            >
              <ToggleGroup.Item
                value="editor"
                className="px-3 py-1.5 text-sm font-medium rounded-md transition-all duration-200 flex items-center gap-1.5 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                </svg>
                Canvas
              </ToggleGroup.Item>
              {/* Paths view disabled for now - selection removed; routes and code remain in place */}
              <ToggleGroup.Item
                value="code"
                className="px-3 py-1.5 text-sm font-medium rounded-md transition-all duration-200 flex items-center gap-1.5 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                </svg>
                Code
              </ToggleGroup.Item>
            </ToggleGroup.Root>

            {/* Settings Button */}
            <div className="ml-auto">
              <button
                onClick={() => setSettingsDialogOpen(true)}
                className="p-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 flex items-center justify-center shadow-sm hover:shadow-md"
                title="Settings"
                aria-label="Settings"
              >
                <Settings className="w-4 h-4" />
              </button>
            </div>

            {/* Canvas Settings Dialog */}
            <CanvasSettingsDialog
              open={settingsDialogOpen}
              onOpenChange={setSettingsDialogOpen}
              clickToFocusEnabled={clickToFocusEnabled}
              snapToGrid={snapToGrid}
              smartGuidesEnabled={smartGuidesEnabled}
              showGrid={showGrid}
              gridSize={gridSize}
              gridStyle={gridStyle}
              canvasBackground={canvasBackground}
              edgeStyling={edgeStyling}
              edgeRouting={edgeRouting}
              edgeAnimation={edgeAnimation}
              onSave={handleSettingsSave}
              searchHistoryCount={searchHistoryCount}
              onClearSearchHistory={clearSearchHistoryFn || undefined}
            />
          </>
        )}
      </div>
      {serverAheadForProject && (
        <div className="mt-2 w-full min-w-0 px-1">
          <ServerAheadPushBanner
            detail={serverAheadForProject.message}
            pullLoading={pullReconcileLoading}
            onPull={handlePullReconcile}
            onOpenMerge={handleOpenMergeFromBanner}
          />
        </div>
      )}
      {(() => {
        const v = versions.find((x) => x.id === localVersionId);
        if (!v || !isRevisionDeprecated(v.metadata)) return null;
        return (
          <RevisionDeprecationBanner
            roleLabel="Studio"
            versionLabel={v.version_id}
            metadata={v.metadata}
          />
        );
      })()}
    </div>
  );
}

